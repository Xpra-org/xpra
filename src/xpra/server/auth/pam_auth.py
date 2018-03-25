# This file is part of Xpra.
# Copyright (C) 2013-2017 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys

from xpra.server.auth.sys_auth_base import SysAuthenticator, init, log
assert init and log #tests will disable logging from here


def check(username, password):
    log("pam check(%s, [..])", username)
    from xpra.server.pam import pam_session #@UnresolvedImport
    session = pam_session(username, password, "login")
    if not session.start(password):
        return False
    success = session.authenticate()
    if success:
        session.close()
    return success


class Authenticator(SysAuthenticator):

    def check(self, password):
        log("pam.check(..) pw=%s", self.pw)
        if self.pw is None:
            return False
        return check(self.username, password)

    def get_challenge(self, digests):
        if "xor" not in digests:
            log.error("Error: pam authentication requires the 'xor' digest")
            return None
        return SysAuthenticator.get_challenge(self, ["xor"])

    def __repr__(self):
        return "PAM"


def main(args):
    if len(args)!=3:
        print("invalid number of arguments")
        print("usage:")
        print("%s username password" % (args[0],))
        return 1
    a = Authenticator(args[1])
    if a.check(args[2]):
        print("success")
        return 0
    else:
        print("failed")
        return -1

if __name__ == "__main__":
    sys.exit(main(sys.argv))
