#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2018 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys

from xpra.server.auth.sys_auth_base import SysAuthenticatorBase, init, log, parse_uid, parse_gid
from xpra.net.crypto import get_salt, get_digests, gendigest
from xpra.util import xor
from xpra.os_util import WIN32
assert init and log #tests will disable logging from here


def init(opts):
    pass


class Authenticator(SysAuthenticatorBase):

    def __init__(self, username, **kwargs):
        self.service = kwargs.pop("service", "")
        self.realm = kwargs.pop("realm", "")
        self.uid = parse_uid(kwargs.pop("uid", None))
        self.gid = parse_gid(kwargs.pop("gid", None))
        username = kwargs.pop("username", username)
        SysAuthenticatorBase.__init__(self, username, **kwargs)
        log("kerberos-password auth: service=%s, realm=%s, username=%s", self.service, self.realm, username)

    def get_uid(self):
        return self.uid

    def get_gid(self):
        return self.gid

    def __repr__(self):
        return "kerberos-password"

    def get_challenge(self, digests):
        if "xor" not in digests:
            log.error("Error: kerberos authentication requires the 'xor' digest")
            return None
        return SysAuthenticatorBase.get_challenge(self, ["xor"])

    def check(self, password):
        try:
            if WIN32:
                import winkerberos as kerberos          #@UnresolvedImport @UnusedImport
            else:
                import kerberos                         #@UnresolvedImport @Reimport
        except ImportError as e:
            log("check(..)", exc_info=True)
            log.warn("Warning: cannot use kerberos password authentication:")
            log.warn(" %s", e)
            return False
        try:
            kerberos.checkPassword(self.username, password, self.service, self.realm)
            return True
        except kerberos.KrbError as e:
            log("check(..)", exc_info=True)
            log.error("Error: kerberos authentication failed:")
            log.error(" %s", e)
            return False


def main(argv):
    from xpra.platform import program_context
    with program_context("Kerberos-Password-Auth", "Kerberos-Password-Authentication"):
        if len(argv) not in (3,4,5):
            sys.stderr.write("%s invalid arguments\n" % argv[0])
            sys.stderr.write("usage: %s username password [service [realm]]\n" % argv[0])
            return 1
        username = argv[1]
        password = argv[2]
        kwargs = {}
        if len(argv)>=4:
            kwargs["service"] = argv[3]
        if len(argv)==5:
            kwargs["realm"] = argv[4]
        a = Authenticator(username, **kwargs)
        server_salt, digest = a.get_challenge(["xor"])
        salt_digest = a.choose_salt_digest(get_digests())
        assert digest=="xor"
        client_salt = get_salt(len(server_salt))
        combined_salt = gendigest(salt_digest, client_salt, server_salt)
        response = xor(password, combined_salt)
        a.authenticate(response, client_salt)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
