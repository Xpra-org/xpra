# This file is part of Xpra.
# Copyright (C) 2013 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.


from xpra.server.auth.sys_auth_base import SysAuthenticator, init, log
import win32security            #@UnresolvedImport
assert win32security            #avoid pydev warning
assert init and log #tests will disable logging from here


class Authenticator(SysAuthenticator):

    def get_uid(self):
        return 0

    def get_gid(self):
        return 0

    def check(self, password):
        win32security.LogonUser(self.username, '', password, win32security.LOGON32_LOGON_NETWORK, win32security.LOGON32_PROVIDER_DEFAULT)
        return True

    def __repr__(self):
        return "win32"
