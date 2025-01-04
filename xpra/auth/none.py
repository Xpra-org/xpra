# This file is part of Xpra.
# Copyright (C) 2014 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from collections.abc import Sequence

from xpra.auth.sys_auth_base import SysAuthenticator
from xpra.util.objects import typedict


class Authenticator(SysAuthenticator):

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.salt = None

    def requires_challenge(self) -> bool:
        return False

    def get_challenge(self, digests: Sequence[str]) -> tuple[bytes, str]:
        return b"", ""

    def get_password(self) -> str:
        return ""

    def authenticate(self, _caps: typedict) -> bool:
        return True

    def __repr__(self):
        return "none"
