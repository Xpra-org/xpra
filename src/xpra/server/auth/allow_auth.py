# This file is part of Xpra.
# Copyright (C) 2013-2016 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.net.crypto import get_salt
from xpra.server.auth.sys_auth_base import SysAuthenticator, init, log
assert init and log #tests will disable logging from here


class Authenticator(SysAuthenticator):

    def __repr__(self):
        return "allow"

    def get_challenge(self):
        return get_salt(), "hmac"

    def get_password(self):
        return None

    def authenticate(self, challenge_response, client_salt):
        return True
