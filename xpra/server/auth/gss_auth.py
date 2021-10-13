#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2018-2021 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys

from xpra.util import typedict
from xpra.server.auth.sys_auth_base import SysAuthenticatorBase, log, parse_uid, parse_gid
from xpra.net.digest import get_salt, get_digests, gendigest


class Authenticator(SysAuthenticatorBase):
    CLIENT_USERNAME = True

    def __init__(self, **kwargs):
        self.service = kwargs.pop("service", "")
        self.uid = parse_uid(kwargs.pop("uid", None))
        self.gid = parse_gid(kwargs.pop("gid", None))
        kwargs["prompt"] = kwargs.pop("prompt", "GSS token")
        super().__init__(**kwargs)
        log("gss auth: service=%r, username=%r", self.service, kwargs.get("username"))

    def get_uid(self) -> int:
        return self.uid

    def get_gid(self) -> int:
        return self.gid

    def __repr__(self):
        return "gss"

    def get_challenge(self, digests):
        assert not self.challenge_sent
        if "gss" not in digests:
            log.error("Error: client does not support gss authentication")
            return None
        self.salt = get_salt()
        self.challenge_sent = True
        return self.salt, "gss:%s" % self.service

    def check(self, token) -> bool:
        log("check(%s)", repr(token))
        assert self.challenge_sent
        try:
            from gssapi import creds as gsscreds
            from gssapi import sec_contexts as gssctx
        except ImportError as e:
            log("check(..)", exc_info=True)
            log.warn("Warning: cannot use gss authentication:")
            log.warn(" %s", e)
            return False
        server_creds = gsscreds.Credentials(usage='accept')
        server_ctx = gssctx.SecurityContext(creds=server_creds)
        server_ctx.step(token)
        return server_ctx.complete


def main(argv):
    from xpra.platform import program_context
    with program_context("GSS-Auth", "GSS-Authentication"):
        if len(argv)!=3:
            sys.stderr.write("%s invalid arguments\n" % argv[0])
            sys.stderr.write("usage: %s username token\n" % argv[0])
            return 1
        username = argv[1]
        token = argv[2]
        kwargs = {"username" : username}
        a = Authenticator(**kwargs)
        server_salt, digest = a.get_challenge(["gss"])
        salt_digest = a.choose_salt_digest(get_digests())
        assert digest.startswith("gss:"), "unexpected digest %r" % digest
        client_salt = get_salt(len(server_salt))
        combined_salt = gendigest(salt_digest, client_salt, server_salt)
        response = gendigest(digest, token, combined_salt)
        caps = typedict({
            "challenge_response"    : response,
            "challenge_client_salt" : client_salt,
            })
        r = a.authenticate(caps)
        print("success: %s" % bool(r))
        return r


if __name__ == "__main__":
    sys.exit(main(sys.argv))
