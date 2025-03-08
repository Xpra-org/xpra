#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2013 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from collections.abc import Sequence

from xpra.platform.win32.auth import check
from xpra.auth.sys_auth_base import SysAuthenticator, log


class Authenticator(SysAuthenticator):

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # fugly: keep hold of the password so the win32 proxy can use it
        self.password = ""

    def verify_username(self, remote_username: str) -> None:
        if remote_username.lower() != self.username.lower():
            log(f"verifying username={self.username!r} vs remote={remote_username!r}")
            raise ValueError(f"invalid username {remote_username!r}")

    def get_uid(self) -> int:
        return 0

    def get_gid(self) -> int:
        return 0

    def get_password(self) -> str:
        return self.password

    def get_challenge(self, digests: Sequence[str]) -> tuple[bytes, str]:
        self.req_xor(digests)
        return super().do_get_challenge(["xor"])

    def check_password(self, password: str) -> bool:
        domain = ""  # os.environ.get('COMPUTERNAME')
        if check(domain, self.username, password):
            self.password = password
            return True
        return False

    def __repr__(self):
        return "win32"


def main(argv) -> int:
    # pylint: disable=import-outside-toplevel
    from xpra.platform import program_context
    from xpra.log import enable_color, consume_verbose_argv
    with program_context("Auth-Test", "Auth-Test"):
        enable_color()
        consume_verbose_argv(argv, "auth")
        if len(argv) != 3:
            log.warn("invalid number of arguments")
            log.warn("usage: %s [--verbose] username password", argv[0])
            return 1
        username = argv[1]
        password = argv[2]
        if check("", username, password):
            log.info("authentication succeeded")
            return 0
        log.error("authentication failed")
        return 1


if __name__ == "__main__":
    import sys

    sys.exit(main(sys.argv))
