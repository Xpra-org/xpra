# This file is part of Xpra.
# Copyright (C) 2014-2017 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.server.auth.sys_auth_base import SysAuthenticator, init, log
from xpra.platform.info import get_username
assert init and log #tests will disable logging from here


class Authenticator(SysAuthenticator):

    def __init__(self, username, **kwargs):
        SysAuthenticator.__init__(self, username or get_username(), **kwargs)
        self.salt = None

    def requires_challenge(self):
        return False

    def get_challenge(self, _digests):
        return None

    def get_password(self):
        return None

    def authenticate(self, _challenge_response=None, _client_salt=None):
        return True

    def __repr__(self):
        return "none"
