#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2018 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import sys
from collections.abc import Sequence

from xpra.util.io import stderr_print
from xpra.util.objects import typedict
from xpra.util.str_fn import obsc
from xpra.auth.sys_auth_base import SysAuthenticatorBase, log
from xpra.auth.common import parse_uid, parse_gid
from xpra.log import is_debug_enabled

assert log  # tests will disable logging from here

LDAP_CACERTFILE = os.environ.get("XPRA_LDAP_CACERTFILE")


class Authenticator(SysAuthenticatorBase):
    CLIENT_USERNAME = True

    def __init__(self, **kwargs):
        self.tls = bool(int(kwargs.pop("tls", "0")))
        self.host = kwargs.pop("host", "localhost")
        self.cacert = kwargs.pop("cacert", LDAP_CACERTFILE)
        self.uid = parse_uid(kwargs.pop("uid", None))
        self.gid = parse_gid(kwargs.pop("gid", None))
        self.tls_version = None
        self.tls_validate = None
        if self.tls:
            import ssl
            tls_version = kwargs.pop("ssl-version", "TLS")
            tls_validate = kwargs.pop("ssl-validate", "REQUIRED")
            self.tls_version = getattr(ssl, "PROTOCOL_%s" % tls_version)
            self.tls_validate = getattr(ssl, "CERT_%s" % tls_validate)
            default_port = 636
        else:
            default_port = 389
        self.port = int(kwargs.pop("port", default_port))
        self.authentication = kwargs.pop("authentication", "NTLM").upper()
        assert self.authentication in ("SIMPLE", "SASL", "NTLM"), \
            "invalid authentication mechanism '%s'" % self.authentication
        super().__init__(**kwargs)
        log("ldap auth: host=%s, port=%i, tls=%s",
            self.host, self.port, self.tls)

    def get_uid(self) -> int:
        return self.uid

    def get_gid(self) -> int:
        return self.gid

    def __repr__(self):
        return "ldap3"

    def get_challenge(self, digests: Sequence[str]) -> tuple[bytes, str]:
        self.req_xor(digests)
        return super().get_challenge(("xor", ))

    def check_password(self, password: str) -> bool:
        log("check_password(%s)", obsc(password))
        try:
            from ldap3 import Server, Connection, Tls, ALL, SIMPLE, SASL, NTLM
        except ImportError as e:
            log("check_password(..)", exc_info=True)
            log.warn("Warning: cannot use ldap3 authentication:")
            log.warn(" %s", e)
            return False
        try:
            MECHANISM = {
                "SIMPLE": SIMPLE,
                "SASL": SASL,
                "NTLM": NTLM,
            }
            authentication: SIMPLE | SASL | NTLM = MECHANISM[self.authentication]
            tls = None
            if self.tls:
                tls = Tls(validate=self.tls_validate, version=self.tls_version, ca_certs_file=self.cacert)
                log("TLS=%s", tls)
            server = Server(self.host, port=self.port, tls=tls, use_ssl=self.tls, get_info=ALL)
            log("ldap3 Server(%s)=%s", (self.host, self.port, self.tls), server)
            conn = Connection(server, user=self.username, password=password,
                              authentication=authentication, receive_timeout=10)
            log("ldap3 Connection(%s, %s, %s)=%s", server, self.username, self.authentication, conn)
            if self.tls:
                conn.start_tls()
            r = conn.bind()
            log("ldap3 %s.bind()=%s", conn, r)
            if not r:
                return False
            if is_debug_enabled("auth"):
                log("ldap3 server info:")
                for line in server.info.splitlines():
                    log(f" {line}")
            log("ldap3 who_am_i()=%s", conn.extend.standard.who_am_i())
            return True
        except Exception as e:
            log("ldap3 check_password(..)", exc_info=True)
            log.error("Error: ldap3 authentication failed:")
            log.estr(e)
            return False


def main(argv) -> int:
    # pylint: disable=import-outside-toplevel
    from xpra.log import consume_verbose_argv
    from xpra.net.digest import get_salt, get_digests, gendigest
    from xpra.platform import program_context
    with program_context("LDAP3-Password-Auth", "LDAP3-Password-Authentication"):
        consume_verbose_argv(argv, "auth")
        if len(argv) not in (3, 4, 5, 6):
            stderr_print("%s invalid arguments" % argv[0])
            stderr_print("usage: %s username password [host] [port] [tls]" % argv[0])
            return 1
        username = argv[1]
        password = argv[2]
        kwargs = {"username": username}
        if len(argv) >= 4:
            kwargs["host"] = argv[3]
        if len(argv) >= 5:
            kwargs["port"] = argv[4]
        if len(argv) >= 6:
            kwargs["tls"] = argv[5]
        a = Authenticator(**kwargs)
        server_salt, digest = a.get_challenge(("xor", ))
        salt_digest = a.choose_salt_digest(get_digests())
        client_salt = get_salt(len(server_salt))
        combined_salt = gendigest(salt_digest, client_salt, server_salt)
        assert digest == "xor"
        response = gendigest(digest, password, combined_salt)
        caps = typedict({
            "challenge_response": response,
            "challenge_client_salt": client_salt,
        })
        r = a.authenticate(caps)
        print("success: %s" % r)
        return int(not r)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
