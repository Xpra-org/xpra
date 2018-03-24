#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2018 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys

from xpra.server.auth.sys_auth_base import SysAuthenticatorBase, init, log
from xpra.net.crypto import get_salt, get_digests, gendigest
from xpra.util import xor
from xpra.os_util import WIN32
assert init and log #tests will disable logging from here

if WIN32:
    import winkerberos as kerberos
else:
    import kerberos


def init(opts):
    pass


class Authenticator(SysAuthenticatorBase):

    def __init__(self, username, **kwargs):
        self.service = kwargs.pop("service", "")
        self.realm = kwargs.pop("realm", "")
        def ipop(k):
            try:
                return int(kwargs.pop(k, 0))
            except ValueError:
                return 0
        self.uid = ipop("uid")
        self.gid = ipop("gid")
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
        assert not self.challenge_sent
        if self.salt is not None:
            log.error("Error: authentication challenge already sent!")
            return None
        if "xor" not in digests:
            log.error("Error: kerberos authentication requires the 'xor' digest")
            return None
        self.salt = get_salt()
        self.challenge_sent = True
        return self.salt, "xor"

    def check(self, password):
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
