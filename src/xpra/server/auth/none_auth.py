# This file is part of Xpra.
# Copyright (C) 2013 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.server.auth.sys_auth_base import SysAuthenticator
import os


def init(opts):
    pass

class Authenticator(SysAuthenticator):

    def __init__(self, username):
        self.salt = None
        self.pw = None
        try:
            import pwd
            self.pw = pwd.getpwuid(os.getuid())
            self.username = self.pw.pw_name
        except:
            import getpass
            self.username = getpass.getuser()

    def requires_challenge(self):
        return False

    def get_challenge(self):
        return None

    def get_password(self):
        return None

    def authenticate(self, challenge_response, client_salt):
        return True
