# This file is part of Xpra.
# Copyright (C) 2013-2019 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import sys

from xpra.util import envbool
from xpra.scripts.config import parse_bool
from xpra.server.auth.sys_auth_base import SysAuthenticator, log

PAM_AUTH_SERVICE = os.environ.get("XPRA_PAM_AUTH_SERVICE", "login")
PAM_CHECK_ACCOUNT = envbool("XPRA_PAM_CHECK_ACCOUNT", False)


def check(username, password, service=PAM_AUTH_SERVICE, check_account=PAM_CHECK_ACCOUNT):
    log("pam check(%s, [..])", username)
    from xpra.server.pam import pam_session #@UnresolvedImport
    session = pam_session(username, password, service)
    if not session.start(password):
        return False
    try:
        success = session.authenticate()
        if success and check_account:
            success = session.check_account()
    finally:
        try:
            session.close()
        except:
            log("error closing session %s", session, exc_info=True)
    return success


class Authenticator(SysAuthenticator):

    def __init__(self, username, **kwargs):
        self.service = kwargs.pop("service", PAM_AUTH_SERVICE)
        self.check_account = parse_bool("check-account", kwargs.pop("check-account", PAM_CHECK_ACCOUNT), False)
        super().__init__(username, **kwargs)

    def check(self, password) -> bool:
        log("pam.check(..) pw=%s", self.pw)
        if self.pw is None:
            return False
        return check(self.username, password, self.service, self.check_account)

    def get_challenge(self, digests):
        if "xor" not in digests:
            log.error("Error: pam authentication requires the 'xor' digest")
            return None
        return super().get_challenge(["xor"])

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
