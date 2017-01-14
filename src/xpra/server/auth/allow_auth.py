# This file is part of Xpra.
# Copyright (C) 2013-2017 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.server.auth.sys_auth_base import SysAuthenticator, init, log
assert init and log #tests will disable logging from here


class Authenticator(SysAuthenticator):

    def __repr__(self):
        return "allow"

    def get_password(self):
        return None

    def authenticate(self, challenge_response, client_salt):
        return True
