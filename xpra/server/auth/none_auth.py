# This file is part of Xpra.
# Copyright (C) 2014-2021 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.server.auth.sys_auth_base import SysAuthenticator
from xpra.util import typedict


class Authenticator(SysAuthenticator):

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.salt = None

    def requires_challenge(self) -> bool:
        return False

    def get_challenge(self, _digests):
        return None

    def get_password(self):
        return None

    def authenticate(self, caps : typedict) -> bool:
        return True

    def __repr__(self):
        return "none"
