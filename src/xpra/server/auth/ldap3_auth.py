#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2018 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import sys
from ldap3 import Server, Connection, Tls, ALL, SIMPLE, SASL, NTLM     #@UnresolvedImport

from xpra.util import csv, obsc
from xpra.server.auth.sys_auth_base import SysAuthenticatorBase, init, log
from xpra.log import enable_debug_for
assert init and log #tests will disable logging from here

def init(opts):
    pass

MECHANISM = {
    "SIMPLE"    : SIMPLE,
    "SASL"      : SASL,
    "NTLM"      : NTLM,
    }


LDAP_CACERTFILE = os.environ.get("XPRA_LDAP_CACERTFILE")


class Authenticator(SysAuthenticatorBase):

    def __init__(self, username, **kwargs):
        self.tls = bool(int(kwargs.pop("tls", "0")))
        self.host = kwargs.pop("host", "localhost")
        self.cacert = kwargs.pop("cacert", LDAP_CACERTFILE)
        self.tls_version = None
        self.tls_validate = None
        if self.tls:
            import ssl
            tls_version = kwargs.pop("ssl-version", "TLSv1")
            tls_validate = kwargs.pop("ssl-validate", "REQUIRED")
            self.tls_version = getattr(ssl, "PROTOCOL_%s" % tls_version)
            self.tls_validate = getattr(ssl, "CERT_%s" % tls_validate)
            default_port = 636
        else:
            default_port = 389
        self.port = int(kwargs.pop("port", default_port))
        self.authentication = kwargs.pop("authentication", "NTLM").upper()
        assert self.authentication in MECHANISM, "invalid authentication mechanism '%s', must be one of: %s" % (self.authentication, csv(MECHANISM.keys()))
        username = kwargs.pop("username", username)
        SysAuthenticatorBase.__init__(self, username, **kwargs)
        log("ldap auth: host=%s, port=%i, tls=%s",
            self.host, self.port, self.tls)

    def get_uid(self):
        return self.uid

    def get_gid(self):
        return self.gid

    def __repr__(self):
        return "ldap"

    def get_challenge(self, digests):
        if "xor" not in digests:
            log.error("Error: ldap authentication requires the 'xor' digest")
            return None
        return SysAuthenticatorBase.get_challenge(self, ["xor"])

    def check(self, password):
        log("check(%s)", obsc(password))
        try:
            authentication = MECHANISM[self.authentication]
            tls = None
            if self.tls:
                tls = Tls(validate=self.tls_validate, version=self.tls_version, ca_certs_file=self.cacert)
                log("TLS=%s", tls)
            server = Server(self.host, port=self.port, tls=tls, use_ssl=self.tls, get_info=ALL)
            log("check Server(%s)=%s", (self.host, self.port, self.tls), server)
            conn = Connection(server, user=self.username, password=password, authentication=authentication, receive_timeout=10)
            if self.tls:
                conn.start_tls()
            r = conn.bind()
            log("check %s.bind()=%s", conn, r)
            if not r:
                return False
            log("check Connection(%s, %s, %s)=%s", server, self.username, self.authentication, conn)
            log("check who_am_i()=%s", conn.extend.standard.who_am_i())
            return True
        except Exception as e:
            log("check(..)", exc_info=True)
            log.error("Error: ldap3 authentication failed:")
            log.error(" %s", e)
            return False


def main(argv):
    from xpra.util import xor
    from xpra.net.crypto import get_salt, get_digests, gendigest
    from xpra.platform import program_context
    with program_context("LDAP3-Password-Auth", "LDAP3-Password-Authentication"):
        for x in list(argv):
            if x=="-v" or x=="--verbose":
                enable_debug_for("auth")
                argv.remove(x)
        if len(argv) not in (3,4,5,6):
            sys.stderr.write("%s invalid arguments\n" % argv[0])
            sys.stderr.write("usage: %s username password [host] [port] [tls]\n" % argv[0])
            return 1
        username = argv[1]
        password = argv[2]
        kwargs = {}
        if len(argv)>=4:
            kwargs["host"] = argv[3]
        if len(argv)>=5:
            kwargs["port"] = argv[4]
        if len(argv)>=6:
            kwargs["tls"] = argv[5]
        a = Authenticator(username, **kwargs)
        server_salt, digest = a.get_challenge(["xor"])
        salt_digest = a.choose_salt_digest(get_digests())
        assert digest=="xor"
        client_salt = get_salt(len(server_salt))
        combined_salt = gendigest(salt_digest, client_salt, server_salt)
        response = xor(password, combined_salt)
        r = a.authenticate(response, client_salt)
        print("success: %s" % r)
        return int(not r)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
