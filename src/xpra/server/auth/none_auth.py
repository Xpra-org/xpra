# This file is part of Xpra.
# Copyright (C) 2014-2019 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.server.auth.sys_auth_base import SysAuthenticator, log
from xpra.platform.info import get_username


class Authenticator(SysAuthenticator):

    def __init__(self, username, **kwargs):
        super().__init__(username or get_username(), **kwargs)
        self.salt = None

    def requires_challenge(self) -> bool:
        return False

    def get_challenge(self, _digests):
        return None

    def get_password(self):
        return None

    def authenticate(self, _challenge_response=None, _client_salt=None) -> bool:
        return True

    def __repr__(self):
        return "none"
