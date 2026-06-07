# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import base64
import os.path
from collections.abc import Sequence

from xpra.auth.common import SessionData, parse_uid, parse_gid
from xpra.auth.file_auth_base import stat_filetime
from xpra.auth.sys_auth_base import SysAuthenticator
from xpra.net.digest import get_salt
from xpra.util.objects import typedict
from xpra.util.parsing import TRUE_OPTIONS
from xpra.log import Logger

log = Logger("auth")

DEFAULT_MECHANISMS = ("SCRAM-SHA3-512", "SCRAM-SHA-512", "SCRAM-SHA-256")
LEGACY_MECHANISMS = ("SCRAM-SHA-1",)
PLUS_SUFFIX = "-PLUS"

StoredCredential = tuple[str, int, bytes, bytes, bytes]
AuthEntry = tuple[str, int, int, list[str], dict[str, str], dict[str, str]]


def csv(value: str | Sequence[str]) -> tuple[str, ...]:
    if isinstance(value, str):
        return tuple(x.strip() for x in value.split(",") if x.strip())
    return tuple(str(x).strip() for x in value if str(x).strip())


def b64decode(data: str) -> bytes:
    return base64.b64decode(data.encode("ascii"), validate=True)


def parse_stored_credential(value: str) -> StoredCredential | None:
    parts = value.split("$")
    if len(parts) != 6 or parts[0] != "SCRAM":
        return None
    mechanism = parts[1].upper()
    iterations = int(parts[2])
    if iterations <= 0:
        raise ValueError("iteration count must be positive")
    return mechanism, iterations, b64decode(parts[3]), b64decode(parts[4]), b64decode(parts[5])


def parse_credential_records(value: str) -> tuple[StoredCredential, ...]:
    records: list[StoredCredential] = []
    for part in csv(value):
        record = parse_stored_credential(part)
        if record:
            records.append(record)
    return tuple(records)


def get_channel_binding(connection, name: str):
    sock = getattr(connection, "_socket", None)
    getter = getattr(sock, "get_channel_binding", None)
    if not getter:
        return None
    try:
        data = getter(name)
    except Exception as e:
        log("cannot get %s channel binding from %s: %s", name, sock, e)
        return None
    if not data:
        return None
    return name, data


class Authenticator(SysAuthenticator):
    CLIENT_USERNAME = True

    def __init__(self, **kwargs):
        self.connection = kwargs.get("connection")
        self.password_filename = kwargs.pop("filename", "")
        if self.password_filename and not os.path.isabs(self.password_filename):
            self.password_filename = os.path.join(kwargs.get("exec_cwd", os.getcwd()), self.password_filename)
        self.legacy_sha1 = str(kwargs.pop("legacy-sha1", "no")).lower() in TRUE_OPTIONS
        self.iterations = int(kwargs.pop("iterations", 0) or 0)
        self.channel_binding_name = kwargs.pop("channel-binding", "tls-unique")
        mechanisms = csv(kwargs.pop("mechanisms", ()))
        if not mechanisms:
            mechanisms = DEFAULT_MECHANISMS + (LEGACY_MECHANISMS if self.legacy_sha1 else ())
        self.configured_mechanisms = tuple(x.upper() for x in mechanisms)
        self.password_filedata: str | dict[str, AuthEntry] = ""
        self.password_filetime = 0.0
        self.scram_mechanism = ""
        self.scram_server = None
        self.pending_challenge: tuple[bytes, str, str] | None = None
        self.sessions: SessionData | None = None
        self.scram_stage = ""
        super().__init__(**kwargs)

    def __repr__(self):
        return "scram"

    def get_supported_mechanisms(self) -> tuple[str, ...]:
        try:
            from scramp import ScramMechanism
            from scramp.core import MECHANISMS
        except ImportError as e:
            raise ValueError(f"python-scramp is not installed: {e}") from None
        channel_binding = self.get_channel_binding()
        supported = []
        for mechanism in self.configured_mechanisms:
            names = (mechanism,)
            if not mechanism.endswith(PLUS_SUFFIX):
                names = (f"{mechanism}{PLUS_SUFFIX}", mechanism)
            for name in names:
                if name.endswith(PLUS_SUFFIX) and channel_binding is None:
                    continue
                if name.startswith("SCRAM-SHA-1") and not self.legacy_sha1:
                    continue
                if name in MECHANISMS:
                    ScramMechanism(name)
                    supported.append(name)
        return tuple(dict.fromkeys(supported))

    def get_channel_binding(self):
        return get_channel_binding(self.connection, self.channel_binding_name)

    def get_challenge(self, digests: Sequence[str]) -> tuple[bytes, str]:
        if self.challenge_sent:
            log.error("challenge already sent!")
            return b"", ""
        mechanisms = self.get_supported_mechanisms()
        requested = tuple(x.split(":", 1)[0].upper() for x in digests)
        for mechanism in mechanisms:
            if mechanism in requested:
                self.scram_mechanism = mechanism
                self.scram_stage = "client-first"
                self.challenge_sent = True
                return get_salt(), f"{mechanism}:client-first"
        raise ValueError("no supported SCRAM digest found")

    def choose_salt_digest(self, digest_modes) -> str:
        # SCRAM handles its own salts; the Xpra salt digest is unused but must be safe.
        return super().choose_salt_digest(digest_modes)

    def authenticate(self, caps: typedict) -> bool:
        ret = self.do_authenticate(caps)
        if ret and self.scram_stage == "done":
            self.passed = True
            log("authentication challenge passed for %s", self)
        return ret

    def get_next_challenge(self) -> tuple[bytes, str, str]:
        if not self.pending_challenge:
            return b"", "", ""
        pending = self.pending_challenge
        self.pending_challenge = None
        return pending

    def do_authenticate(self, caps: typedict) -> bool:
        if not self.validate_caps(caps):
            return False
        response = caps.bytesget("challenge_response")
        try:
            if self.scram_stage == "client-first":
                return self.handle_client_first(response)
            if self.scram_stage == "client-final":
                return self.handle_client_final(response)
            if self.scram_stage == "server-final":
                return self.handle_server_final(response)
        except Exception as e:
            log("scram authentication failure", exc_info=True)
            log.warn("Warning: SCRAM authentication failed for %r", self.username)
            log.warn(" %s", e)
        return False

    def handle_client_first(self, response: bytes) -> bool:
        from scramp import ScramMechanism
        mechanism = ScramMechanism(self.scram_mechanism)
        self.scram_server = mechanism.make_server(self.auth_fn, channel_binding=self.get_channel_binding())
        self.scram_server.set_client_first(response.decode("ascii"))
        server_first = self.scram_server.get_server_first().encode("ascii")
        self.scram_stage = "client-final"
        self.pending_challenge = server_first, f"{self.scram_mechanism}:server-first", self.prompt
        return True

    def handle_client_final(self, response: bytes) -> bool:
        if not self.scram_server:
            return False
        self.scram_server.set_client_final(response.decode("ascii"))
        server_final = self.scram_server.get_server_final().encode("ascii")
        self.scram_stage = "server-final"
        self.pending_challenge = server_final, f"{self.scram_mechanism}:server-final", self.prompt
        return True

    def handle_server_final(self, response: bytes) -> bool:
        if response != b"OK":
            log.warn("Warning: SCRAM client did not acknowledge server signature")
            return False
        self.scram_stage = "done"
        return True

    def auth_fn(self, username: str):
        if username != self.username:
            raise ValueError(f"invalid SCRAM username {username!r}")
        entry = self.get_auth_info()
        if not entry:
            raise ValueError(f"no SCRAM credentials for {self.username!r}")
        credential, uid, gid, displays, env_options, session_options = entry
        self.sessions = uid, gid, displays, env_options, session_options
        for mechanism, iterations, salt, stored_key, server_key in parse_credential_records(credential):
            if mechanism == self.scram_mechanism:
                return salt, stored_key, server_key, iterations
        from scramp import ScramMechanism
        mechanism = ScramMechanism(self.scram_mechanism)
        iteration_count = self.iterations or mechanism.iteration_count
        return mechanism.make_auth_info(credential, iteration_count=iteration_count)

    def get_auth_info(self) -> AuthEntry | None:
        data = self.load_password_file()
        if isinstance(data, dict):
            return data.get(self.username)
        if isinstance(data, str) and data:
            return data, parse_uid(None), parse_gid(None), [], {}, {}
        return None

    def load_password_file(self) -> str | dict[str, AuthEntry]:
        if not self.password_filename:
            return ""
        full_path = os.path.abspath(self.password_filename)
        if not os.path.exists(self.password_filename):
            log.error("Error: password file '%s' is missing", full_path)
            self.password_filedata = ""
            return ""
        ptime = stat_filetime(full_path)
        if self.password_filedata and ptime == self.password_filetime:
            return self.password_filedata
        self.password_filetime = 0
        try:
            with open(self.password_filename, encoding="utf8") as f:
                data = f.read()
            self.password_filedata = self.parse_filedata(data)
            self.password_filetime = ptime
        except Exception as e:
            log.error("Error reading password data from '%s':", self.password_filename, exc_info=True)
            log.estr(e)
            self.password_filedata = ""
        return self.password_filedata

    def parse_filedata(self, data: str) -> str | dict[str, AuthEntry]:
        data = data.strip()
        if not data:
            return ""
        lines = [x.strip() for x in data.splitlines() if x.strip() and not x.strip().startswith("#")]
        if not any("|" in x for x in lines):
            return "\n".join(lines)
        auth_data: dict[str, AuthEntry] = {}
        for line in lines:
            fields = line.split("|")
            if len(fields) < 2:
                continue
            username, credential = fields[:2]
            uid = parse_uid(fields[2] if len(fields) >= 3 else None)
            gid = parse_gid(fields[3] if len(fields) >= 4 else None)
            displays = fields[4].split(",") if len(fields) >= 5 and fields[4] else []
            env_options: dict[str, str] = {}
            session_options: dict[str, str] = {}
            if len(fields) >= 6 and fields[5]:
                from xpra.util.parsing import parse_str_dict
                env_options = parse_str_dict(fields[5], ";")
            if len(fields) >= 7 and fields[6]:
                from xpra.util.parsing import parse_str_dict
                session_options = parse_str_dict(fields[6], ";")
            auth_data[username] = credential, uid, gid, displays, env_options, session_options
        return auth_data

    def get_sessions(self) -> SessionData | None:
        return self.sessions or super().get_sessions()
