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
    import winkerberos as kerberos          #@UnresolvedImport @UnusedImport
else:
    import kerberos                         #@Reimport


def init(opts):
    pass


class Authenticator(SysAuthenticatorBase):

    def __init__(self, username, **kwargs):
        def ipop(k):
            try:
                return int(kwargs.pop(k, 0))
            except ValueError:
                return 0
        self.service = kwargs.pop("service", "")
        self.uid = ipop("uid")
        self.gid = ipop("gid")
        username = kwargs.pop("username", username)
        kwargs["prompt"] = kwargs.pop("prompt", "kerberos token")
        SysAuthenticatorBase.__init__(self, username, **kwargs)
        log("kerberos-token auth: service=%s, username=%s", self.service, username)

    def get_uid(self):
        return self.uid

    def get_gid(self):
        return self.gid

    def __repr__(self):
        return "kerberos-token"

    def get_challenge(self, digests):
        assert not self.challenge_sent
        if "kerberos" not in digests:
            log.error("Error: client does not support kerberos authentication")
            return None
        self.salt = get_salt()
        self.challenge_sent = True
        return self.salt, "kerberos:%s" % self.service

    def check(self, token):
        log("check(%r)", token)
        assert self.challenge_sent
        v, ctx = kerberos.authGSSServerInit(self.service)
        if v!=1:
            log.error("Error: kerberos GSS server init failed for service '%s'", self.service)
            return False
        try:
            r = kerberos.authGSSServerStep(ctx, token)
            log("kerberos auth server step result: %s", r==1)
            if r!=1:
                return False
            targetname = kerberos.authGSSServerTargetName(ctx)
            #response = kerberos.authGSSServerResponse(ctx)
            principal = kerberos.authGSSServerUserName(ctx)
            #ie: user1@LOCALDOMAIN
            #maybe we should validate the realm?
            log("kerberos targetname=%s, principal=%s", targetname, principal)
            return True
        finally:
            kerberos.authGSSServerClean(ctx)


def main(argv):
    from xpra.platform import program_context
    with program_context("Kerberos-Token-Auth", "Kerberos Token Authentication"):
        if len(argv)!=3:
            sys.stderr.write("%s invalid arguments\n" % argv[0])
            sys.stderr.write("usage: %s username token\n" % argv[0])
            return 1
        username = argv[1]
        token = argv[2]
        kwargs = {}
        a = Authenticator(username, **kwargs)
        server_salt, digest = a.get_challenge(["xor"])
        salt_digest = a.choose_salt_digest(get_digests())
        assert digest=="xor"
        client_salt = get_salt(len(server_salt))
        combined_salt = gendigest(salt_digest, client_salt, server_salt)
        response = xor(token, combined_salt)
        a.authenticate(response, client_salt)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
