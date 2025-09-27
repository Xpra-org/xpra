# This file is part of Xpra.
# Copyright (C) 2014 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from collections.abc import Sequence

from xpra.auth.common import SessionData
from xpra.net.digest import get_salt, choose_digest
from xpra.util.objects import typedict


class Authenticator:
    def __init__(self, **kwargs):
        self.challenge_sent = False
        self.prompt: str = kwargs.pop("prompt", "password")
        self.passed: bool = False

    def cleanup(self):
        """ no need to do anything """

    def requires_challenge(self) -> bool:
        return True

    def get_challenge(self, digests: Sequence[str]) -> tuple[bytes, str]:
        self.challenge_sent = True
        return get_salt(), choose_digest(digests)

    def choose_salt_digest(self, digest_modes: Sequence[str]) -> str:
        return choose_digest(digest_modes)

    def get_uid(self) -> int:
        return -1

    def get_gid(self) -> int:
        return -1

    def get_passwords(self) -> Sequence[str]:
        return ()

    def get_password(self) -> str:
        return ""

    def authenticate(self, _caps: typedict) -> bool:  # pylint: disable=unused-argument
        return False

    def get_sessions(self) -> SessionData | None:
        return None

    def __repr__(self):
        return "reject"
