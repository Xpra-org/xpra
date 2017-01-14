# This file is part of Xpra.
# Copyright (C) 2014-2017 Antoine Martin <antoine@devloop.org.uk>
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

    def get_challenge(self, digests):
        return None

    def get_password(self):
        return None

    def authenticate(self, challenge_response, client_salt):
        return True

    def __repr__(self):
        return "none"
