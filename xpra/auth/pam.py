# This file is part of Xpra.
# Copyright (C) 2013 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import sys
from collections.abc import Sequence

from xpra.util.env import envbool
from xpra.os_util import getuid
from xpra.util.parsing import str_to_bool
from xpra.auth.sys_auth_base import SysAuthenticator, log

PAM_AUTH_SERVICE = os.environ.get("XPRA_PAM_AUTH_SERVICE", "login")
PAM_CHECK_ACCOUNT = envbool("XPRA_PAM_CHECK_ACCOUNT", False)


def check(username: str, password: str, service: str = PAM_AUTH_SERVICE,
          check_account: bool = PAM_CHECK_ACCOUNT) -> bool:
    log("pam check(%r, ..)", username)
    from xpra.platform.pam import pam_session  # pylint: disable=import-outside-toplevel
    session = pam_session(username, password, service)
    if not session.start(password):
        return False
    try:
        success: bool = session.authenticate()
        if success and check_account:
            success = session.check_account()
        return success
    except Exception as e:
        log.error("Error during pam authentication check")
        log.estr(e)
        return False
    finally:
        try:
            session.close()
        except Exception:
            log("error closing session %s", session, exc_info=True)


class Authenticator(SysAuthenticator):
    CLIENT_USERNAME = getuid() == 0

    def __init__(self, **kwargs):
        self.service = kwargs.pop("service", PAM_AUTH_SERVICE)
        self.check_account = str_to_bool(kwargs.pop("check-account", PAM_CHECK_ACCOUNT))
        super().__init__(**kwargs)

    def check_password(self, password: str) -> bool:
        log("pam.check_password(..) pw=%s", self.pw)
        if self.pw is None:
            return False
        return check(self.username, password, self.service, self.check_account)

    def get_challenge(self, digests: Sequence[str]) -> tuple[bytes, str]:
        self.req_xor(digests)
        return super().do_get_challenge(["xor"])

    def __repr__(self):
        return "PAM"


def main(args) -> int:
    if len(args) != 3:
        print("invalid number of arguments")
        print("usage:")
        print(f"{args[0]} username password")
        return 1
    username = args[1]
    a = Authenticator(username=username)
    if a.check(args[2]):
        print("success")
        return 0
    print("failed")
    return -1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
