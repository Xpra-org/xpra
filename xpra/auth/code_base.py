# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

"""Shared logic for authenticators that deliver a one-time code out of band (email, sms)."""

import hmac
import os
import secrets
import shlex
import ssl
from collections import deque
from collections.abc import Sequence
from ipaddress import ip_address
from subprocess import DEVNULL, PIPE, Popen, TimeoutExpired
from threading import Event, Lock, Thread
from time import monotonic

from xpra.auth.sys_auth_base import SysAuthenticator, log
from xpra.net.digest import choose_digest, gendigest, get_salt
from xpra.net.tls.parsing import parse_ssl_options_mask, parse_ssl_protocol, parse_ssl_verify_mask, parse_ssl_verify_mode
from xpra.util.objects import typedict
from xpra.util.parsing import ALL_BOOLEAN_OPTIONS, TRUE_OPTIONS, parse_encoded_bin_data

OUTPUT_LIMIT = 4096
SSL_OPTIONS = (
    "ca-certs", "ca-data", "cert", "key", "key-password-file", "check-hostname", "server-verify-mode",
    "protocol", "verify-flags", "options", "ciphers",
)


def pop_positive(kwargs: dict, name: str, default: int, maximum: int = 86400) -> int:
    value = int(kwargs.pop(name, default))
    if not 1 <= value <= maximum:
        raise ValueError(f"{name} must be between 1 and {maximum}")
    return value


def read_secret_file(filename: str) -> str:
    with open(filename, encoding="utf-8") as f:
        return f.read().removesuffix("\n").removesuffix("\r")


def lookup_command(command: Sequence[str], username: str, timeout: int) -> str:
    """Bound both the helper's stdout and the time spent reading / waiting."""
    output: list[bytes] = []
    finished = Event()
    deadline = monotonic() + timeout
    with Popen((*command, username), stdin=DEVNULL, stdout=PIPE, stderr=DEVNULL, bufsize=0) as proc:
        def read_output() -> None:
            data = bytearray()
            try:
                while len(data) <= OUTPUT_LIMIT:
                    chunk = proc.stdout.read(OUTPUT_LIMIT + 1 - len(data))
                    if not chunk:
                        output.append(bytes(data))
                        return
                    data.extend(chunk)
            except (OSError, ValueError):
                pass
            finally:
                finished.set()

        reader = Thread(target=read_output, name="code-destination-lookup", daemon=True)
        reader.start()
        try:
            if not finished.wait(max(0, deadline - monotonic())):
                raise ValueError("lookup command timed out")
            if not output:
                raise ValueError("lookup command output exceeds limit or cannot be read")
            if proc.wait(timeout=max(0, deadline - monotonic())) != 0:
                raise ValueError("lookup command failed")
        except TimeoutExpired:
            raise ValueError("lookup command timed out") from None
        finally:
            if proc.poll() is None:
                proc.kill()
            proc.wait()
            proc.stdout.close()
            reader.join(timeout=0.1)
    # Permit one line terminator from a command-line helper, never lists.
    return output[0].decode("utf-8").removesuffix("\n").removesuffix("\r")


def pop_ssl_options(kwargs: dict, prefix: str, cwd: str) -> dict:
    """Consume the `{prefix}ssl-*` module options, eg: `smtp-ssl-ca-certs`."""
    options = {name: kwargs.pop(f"{prefix}ssl-{name}") for name in SSL_OPTIONS if f"{prefix}ssl-{name}" in kwargs}
    if any(name.startswith(f"{prefix}ssl-") for name in kwargs):
        raise ValueError(f"unsupported {prefix}ssl option")
    if "check-hostname" in options:
        value = str(options["check-hostname"]).lower()
        if value not in ALL_BOOLEAN_OPTIONS:
            raise ValueError(f"{prefix}ssl-check-hostname must be a boolean")
        options["check-hostname"] = value in TRUE_OPTIONS
    if any(options.get(name) for name in ("key", "key-password-file")) and not options.get("cert"):
        raise ValueError(f"{prefix}ssl-key and {prefix}ssl-key-password-file require {prefix}ssl-cert")
    for name in ("ca-certs", "cert", "key", "key-password-file"):
        path = options.get(name)
        if path and not (name == "ca-certs" and path == "default"):
            options[name] = os.path.join(cwd, path)
    return options


def make_ssl_context(settings: dict) -> ssl.SSLContext:
    context = ssl.create_default_context()
    if "protocol" in settings:
        protocol = parse_ssl_protocol(settings["protocol"], server_side=False)
        if protocol == ssl.PROTOCOL_TLS_SERVER:
            raise ValueError("a client SSL protocol is required")
        if protocol != context.protocol:
            defaults = context
            context = ssl.SSLContext(protocol)
            context.options |= defaults.options
            context.verify_flags = defaults.verify_flags
            context.verify_mode = defaults.verify_mode
            context.check_hostname = defaults.check_hostname
            context.load_default_certs()
    verify_mode = parse_ssl_verify_mode(settings.get("server-verify-mode", "required"))
    check_hostname = settings.get("check-hostname", verify_mode != ssl.CERT_NONE)
    if check_hostname and verify_mode == ssl.CERT_NONE:
        raise ValueError("hostname checking requires certificate verification")
    context.check_hostname = False
    context.verify_mode = verify_mode
    context.check_hostname = check_hostname
    if "verify-flags" in settings:
        context.verify_flags = parse_ssl_verify_mask(settings["verify-flags"].replace("+", ","))
    if "options" in settings:
        context.options |= parse_ssl_options_mask(settings["options"].replace("+", ","))
    if "ciphers" in settings:
        context.set_ciphers(settings["ciphers"])
    ca_certs = settings.get("ca-certs")
    if ca_certs and ca_certs != "default":
        if os.path.isdir(ca_certs):
            context.load_verify_locations(capath=ca_certs)
        else:
            context.load_verify_locations(cafile=ca_certs)
    if "ca-data" in settings:
        ca_data = settings["ca-data"]
        if not ca_data.startswith("-----BEGIN CERTIFICATE-----"):
            ca_data = parse_encoded_bin_data(ca_data)
        if not ca_data:
            raise ValueError("invalid ssl-ca-data")
        context.load_verify_locations(cadata=ca_data)
    if settings.get("cert"):
        password = ""
        if settings.get("key-password-file"):
            password = read_secret_file(settings["key-password-file"])
        # An explicit password, including an empty one, prevents interactive OpenSSL prompts.
        context.load_cert_chain(settings["cert"], settings.get("key") or None, password=password)
    return context


class CodeAuthenticator(SysAuthenticator):
    """
    Sends a one-time code to a destination (mailbox, phone number, ..)
    which may first be prompted for, then verifies it using an HMAC challenge.
    Subclasses implement `validate_destination` and `send_code`,
    and must define their own `SENDS` and `SEND_LOCK` so that each kind has its own send limits.
    """
    __slots__ = (
        "address", "cancelled", "code", "code_digest", "code_prompt", "command", "connection", "digits", "expires",
        "lock", "lookup", "lookup_timeout", "mode", "pending_challenge", "query", "state", "timeout", "uri",
    )
    CLIENT_USERNAME = True
    KIND = "code"
    DESTINATION_OPTION = "address"
    MODES = ("fixed", "prompt", "lookup")
    DEFAULT_QUERY = ""
    MAX_RESPONSE = 254
    SENDS: dict[tuple[str, str], deque[float]]
    SEND_LOCK: Lock
    MAX_SEND_KEYS = 10000

    def __init__(self, **kwargs):
        self.mode = kwargs.pop("mode", "fixed")
        if self.mode not in self.MODES:
            raise ValueError("mode must be one of " + ", ".join(self.MODES))
        self.address = kwargs.pop(self.DESTINATION_OPTION, "")
        self.lookup = kwargs.pop("lookup", "")
        self.uri = kwargs.pop("uri", "")
        self.query = kwargs.pop("query", self.DEFAULT_QUERY)
        self.command = shlex.split(kwargs.pop("command", ""))
        self.lookup_timeout = pop_positive(kwargs, "lookup-timeout", 10)
        self.digits = pop_positive(kwargs, "digits", 6, 12)
        if self.digits < 6:
            raise ValueError("digits must be at least 6")
        self.timeout = pop_positive(kwargs, "timeout", 120)
        if self.mode == "lookup":
            if self.lookup not in ("sql", "exec"):
                raise ValueError("lookup must be sql or exec")
            if self.lookup == "sql" and not (self.uri and self.query):
                raise ValueError("SQL lookup requires uri and query")
            if self.lookup == "exec" and not self.command:
                raise ValueError("exec lookup requires command")
        self.connection = kwargs.get("connection")
        self.lock = Lock()
        self.cancelled = Event()
        self.code = self.code_digest = ""
        self.expires = 0.0
        self.state = "new"
        self.pending_challenge: tuple[bytes, str, str] | None = None
        super().__init__(**kwargs)
        self.code_prompt = self.prompt

    def __repr__(self):
        return self.KIND

    def get_uid(self) -> int:
        return -1

    def get_gid(self) -> int:
        return -1

    def get_sessions(self) -> None:
        return None

    def validate_destination(self, value: str) -> str:
        raise NotImplementedError()

    def send_code(self, address: str, code: str) -> None:
        raise NotImplementedError()

    def get_destination_prompt(self) -> str:
        raise NotImplementedError()

    def parse_prompted_destination(self, value: str) -> str:
        return self.validate_destination(value)

    def derive_destination(self) -> str:
        raise ValueError(f"{self.mode!r} mode is not supported")

    def resolve_address(self) -> str:
        if self.mode == "fixed":
            return self.address
        if self.mode != "lookup":
            return self.derive_destination()
        if not self.username or len(self.username) > 1024 or any(ord(c) < 32 for c in self.username):
            raise ValueError("invalid lookup username")
        if self.lookup == "exec":
            return self.validate_destination(lookup_command(self.command, self.username, self.lookup_timeout))
        from sqlalchemy import create_engine, text
        engine = create_engine(self.uri, hide_parameters=True)
        try:
            with engine.connect() as connection:
                with connection.execute(text(self.query), {"username": self.username}) as result:
                    rows = result.fetchmany(2)
                    if len(rows) != 1 or len(rows[0]) != 1:
                        raise ValueError("SQL lookup must return one row with one value")
                    value = rows[0][0]
                    if not isinstance(value, str):
                        raise ValueError("SQL lookup must return a string")
                    return self.validate_destination(value)
        finally:
            engine.dispose()

    def reserve_send(self, address: str) -> None:
        now = monotonic()
        # Keep the destination's case for delivery, but fold it for the limiter.
        keys = [("recipient", address.lower())]
        remote = getattr(self.connection, "remote", None)
        if isinstance(remote, (tuple, list)) and remote:
            try:
                peer = ip_address(str(remote[0]).split("%", 1)[0])
                peer = getattr(peer, "ipv4_mapped", None) or peer
                keys.append(("peer", str(peer)))
            except ValueError:
                pass
        with self.SEND_LOCK:
            for key, attempts in tuple(self.SENDS.items()):
                window = 60 if key[0] == "recipient" else 300
                while attempts and attempts[0] <= now - window:
                    attempts.popleft()
                if not attempts:
                    del self.SENDS[key]
            if len(self.SENDS) + sum(key not in self.SENDS for key in keys) > self.MAX_SEND_KEYS:
                raise ValueError(f"{self.KIND} send tracking limit reached")
            for key in keys:
                limit = 1 if key[0] == "recipient" else 5
                if len(self.SENDS.get(key, ())) >= limit:
                    raise ValueError(f"{self.KIND} send rate limit reached")
            for key in keys:
                self.SENDS.setdefault(key, deque()).append(now)

    def issue_code(self, address: str) -> tuple[bytes, str]:
        if self.cancelled.is_set():
            raise ValueError(f"{self.KIND} authentication cancelled")
        self.reserve_send(address)
        code = f"{secrets.randbelow(10 ** self.digits):0{self.digits}d}"
        self.send_code(address, code)
        with self.lock:
            if self.cancelled.is_set():
                raise ValueError(f"{self.KIND} authentication cancelled")
            self.code = code
            self.expires = monotonic() + self.timeout
            self.state = "code"
            self.salt = get_salt()
            self.digest = self.code_digest
            self.prompt = self.code_prompt
            self.challenge_sent = True
            return self.salt, self.digest

    def get_challenge(self, digests: Sequence[str]) -> tuple[bytes, str]:
        with self.lock:
            if self.state != "new" or self.cancelled.is_set():
                return b"", ""
            self.state = "sending"
        try:
            self.code_digest = choose_digest(tuple(d for d in digests if d.startswith("hmac+")))
            if self.mode == "prompt":
                self.req_xor(digests)
                with self.lock:
                    if self.cancelled.is_set():
                        raise ValueError(f"{self.KIND} authentication cancelled")
                    self.state = "address"
                    self.prompt = self.get_destination_prompt()
                    return self.do_get_challenge(("xor",))
            return self.issue_code(self.resolve_address())
        except Exception:
            self.cleanup()
            # Do not expose provider replies, lookup output or credentials.
            raise ValueError(f"cannot issue {self.KIND} authentication challenge") from None

    def get_next_challenge(self) -> tuple[()] | tuple[bytes, str, str]:
        with self.lock:
            pending = self.pending_challenge
            self.pending_challenge = None
            return pending or ()

    def authenticate(self, caps: typedict) -> bool:
        try:
            with self.lock:
                if self.cancelled.is_set() or self.state not in ("address", "code") or not self.salt or not self.validate_caps(caps):
                    raise ValueError(f"unexpected {self.KIND} authentication response")
                if self.state == "code":
                    salt = self.get_response_salt(caps.bytesget("challenge_client_salt"))
                    expected = gendigest(self.digest, self.code, salt)
                    valid = monotonic() < self.expires and hmac.compare_digest(expected, caps.bytesget("challenge_response"))
                    self.code = ""
                    self.expires = 0.0
                    self.state = "complete" if valid else "failed"
                    self.passed = valid
                    return valid
                response = caps.bytesget("challenge_response")
                if len(response) > self.MAX_RESPONSE:
                    raise ValueError(f"{self.KIND} destination response too long")
                # Use bytes here: decoding a random client salt as text can corrupt it.
                salt = self.get_response_salt(caps.bytesget("challenge_client_salt"))
                value = gendigest("xor", response, salt).decode("ascii")
                address = self.parse_prompted_destination(value)
                self.state = "sending"
            salt, digest = self.issue_code(address)
            with self.lock:
                if self.cancelled.is_set():
                    return False
                self.pending_challenge = salt, digest, self.prompt
            return True
        except Exception:
            log.warn(f"Warning: {self.KIND} authentication failed")
        self.cleanup()
        return False

    def cleanup(self) -> None:
        self.cancelled.set()
        with self.lock:
            self.code = ""
            self.expires = 0.0
            self.salt = None
            self.pending_challenge = None
            if self.state != "complete":
                self.state = "failed"
