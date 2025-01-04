#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2018 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys
from collections.abc import Sequence

from xpra.auth.sys_auth_base import SysAuthenticatorBase, xor, log
from xpra.auth.common import parse_uid, parse_gid
from xpra.net.digest import get_salt, get_digests, gendigest
from xpra.util.objects import typedict
from xpra.os_util import WIN32
from xpra.util.io import stderr_print


class Authenticator(SysAuthenticatorBase):
    CLIENT_USERNAME = True

    def __init__(self, **kwargs):
        self.service = kwargs.pop("service", "")
        self.realm = kwargs.pop("realm", "")
        self.uid = parse_uid(kwargs.pop("uid", None))
        self.gid = parse_gid(kwargs.pop("gid", None))
        super().__init__(**kwargs)
        log("kerberos-password auth: service=%r, realm=%r, username=%r",
            self.service, self.realm, kwargs.get("username"))

    def get_uid(self) -> int:
        return self.uid

    def get_gid(self) -> int:
        return self.gid

    def __repr__(self):
        return "kerberos-password"

    def get_challenge(self, digests: Sequence[str]) -> tuple[bytes, str]:
        if "xor" not in digests:
            log.error("Error: kerberos authentication requires the 'xor' digest")
            return b"", ""
        return super().get_challenge(("xor", ))

    def check_password(self, password: str) -> bool:
        try:
            if WIN32:
                import winkerberos as kerberos
            else:
                import kerberos  # @Reimport
        except ImportError as e:
            log("check(..)", exc_info=True)
            log.warn("Warning: cannot use kerberos password authentication:")
            log.warn(" %s", e)
            return False
        try:
            kerberos.checkPassword(self.username, password, self.service, self.realm)  # @UndefinedVariable
            return True
        except kerberos.KrbError as e:  # @UndefinedVariable
            log("check(..)", exc_info=True)
            log.error("Error: kerberos authentication failed:")
            log.estr(e)
            return False


def main(argv) -> int:
    # pylint: disable=import-outside-toplevel
    from xpra.platform import program_context
    with program_context("Kerberos-Password-Auth", "Kerberos-Password-Authentication"):
        if len(argv) not in (3, 4, 5):
            stderr_print("%s invalid arguments" % argv[0])
            stderr_print("usage: %s username password [service [realm]]" % argv[0])
            return 1
        username = argv[1]
        password = argv[2]
        kwargs = {"username": username}
        if len(argv) >= 4:
            kwargs["service"] = argv[3]
        if len(argv) == 5:
            kwargs["realm"] = argv[4]
        a = Authenticator(**kwargs)
        server_salt, digest = a.get_challenge(("xor", ))
        salt_digest = a.choose_salt_digest(get_digests())
        assert digest == "xor"
        client_salt = get_salt(len(server_salt))
        combined_salt = gendigest(salt_digest, client_salt, server_salt)
        response = xor(password, combined_salt)
        caps = typedict({
            "challenge_response": response,
            "challenge_client_salt": client_salt,
        })
        a.authenticate(caps)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
