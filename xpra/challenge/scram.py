# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
from collections.abc import Sequence

from xpra.challenge.handler import AuthenticationHandler
from xpra.platform.info import get_username
from xpra.util.io import load_binary_file
from xpra.util.objects import typedict
from xpra.util.parsing import TRUE_OPTIONS
from xpra.log import Logger

log = Logger("auth")

DEFAULT_MECHANISMS = ("SCRAM-SHA3-512", "SCRAM-SHA-512", "SCRAM-SHA-256")
LEGACY_MECHANISMS = ("SCRAM-SHA-1",)
PLUS_SUFFIX = "-PLUS"


def csv(value: str | Sequence[str]) -> tuple[str, ...]:
    if isinstance(value, str):
        return tuple(x.strip() for x in value.split(",") if x.strip())
    return tuple(str(x).strip() for x in value if str(x).strip())


def get_channel_binding(protocol, name: str):
    conn = getattr(protocol, "_conn", None)
    sock = getattr(conn, "_socket", None)
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


class Handler(AuthenticationHandler):

    def __init__(self, **kwargs):
        self.protocol = kwargs.get("protocol")
        self.display_desc = typedict(kwargs.get("display-desc", {}))
        self.password = kwargs.get("password")
        self.password_files = list(kwargs.get("password-files", ()))
        self.challenge_prompt_function = kwargs.get("challenge_prompt_function")
        self.legacy_sha1 = str(kwargs.get("legacy-sha1", "no")).lower() in TRUE_OPTIONS
        self.channel_binding_name = kwargs.get("channel-binding", "tls-unique")
        mechanisms = csv(kwargs.get("mechanisms", ()))
        if not mechanisms:
            mechanisms = DEFAULT_MECHANISMS + (LEGACY_MECHANISMS if self.legacy_sha1 else ())
        self.configured_mechanisms = tuple(x.upper() for x in mechanisms)
        self.scram_client = None
        self.scram_stage = ""
        self.done = False

    def __repr__(self):
        return "scram"

    def get_digests(self) -> Sequence[str]:
        try:
            from scramp import ScramMechanism
            from scramp.core import MECHANISMS
        except ImportError:
            return ()
        channel_binding = self.get_channel_binding()
        digests: list[str] = []
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
                    digests.append(name)
        return tuple(dict.fromkeys(digests))

    def is_done(self) -> bool:
        return self.done

    def get_channel_binding(self):
        return get_channel_binding(self.protocol, self.channel_binding_name)

    def get_scram_channel_binding(self, mechanism: str):
        if mechanism.endswith(PLUS_SUFFIX):
            return self.get_channel_binding()
        return None

    def get_password(self, prompt: str) -> str:
        if self.password:
            return str(self.password)
        while self.password_files:
            filename = os.path.expanduser(self.password_files.pop(0))
            data = load_binary_file(filename)
            if data:
                return data.decode("utf8")
        if password := os.environ.get("XPRA_PASSWORD"):
            return password
        if self.challenge_prompt_function:
            password = self.challenge_prompt_function(prompt)
            if password:
                return str(password)
        return ""

    def get_username(self) -> str:
        return self.display_desc.strget("username") or get_username()

    def handle(self, challenge: bytes, digest: str, prompt: str):
        mechanism, stage = self.parse_digest(digest)
        if stage == "client-first":
            return self.handle_client_first(mechanism, prompt)
        if stage == "server-first":
            return self.handle_server_first(challenge)
        if stage == "server-final":
            return self.handle_server_final(challenge)
        return b""

    def parse_digest(self, digest: str) -> tuple[str, str]:
        mechanism, _, stage = digest.partition(":")
        if mechanism not in self.get_digests():
            raise ValueError(f"unsupported SCRAM mechanism {mechanism!r}")
        if stage not in ("client-first", "server-first", "server-final"):
            raise ValueError(f"unsupported SCRAM stage {stage!r}")
        return mechanism, stage

    def handle_client_first(self, mechanism: str, prompt: str) -> bytes:
        from scramp import ScramClient
        password = self.get_password(prompt)
        if not password:
            return b""
        self.scram_client = ScramClient((mechanism,), self.get_username(), password,
                                        channel_binding=self.get_scram_channel_binding(mechanism))
        self.scram_stage = "server-first"
        self.done = False
        return self.scram_client.get_client_first().encode("ascii")

    def handle_server_first(self, challenge: bytes) -> bytes:
        if not self.scram_client or self.scram_stage != "server-first":
            raise ValueError("unexpected SCRAM server-first challenge")
        self.scram_client.set_server_first(challenge.decode("ascii"))
        self.scram_stage = "server-final"
        return self.scram_client.get_client_final().encode("ascii")

    def handle_server_final(self, challenge: bytes) -> bytes:
        if not self.scram_client or self.scram_stage != "server-final":
            raise ValueError("unexpected SCRAM server-final challenge")
        self.scram_client.set_server_final(challenge.decode("ascii"))
        self.done = True
        return b"OK"
