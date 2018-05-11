#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2018 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import sys
import socket

from xpra.util import envint, obsc
from xpra.os_util import bytestostr
from xpra.server.auth.sys_auth_base import SysAuthenticatorBase, init, log, parse_uid, parse_gid
from xpra.log import is_debug_enabled, enable_debug_for
assert init and log #tests will disable logging from here

def init(opts):
    pass

LDAP_REFERRALS = envint("XPRA_LDAP_REFERRALS", 0)
LDAP_PROTOCOL_VERSION = envint("XPRA_LDAP_PROTOCOL_VERSION", 3)
LDAP_TRACE_LEVEL = envint("XPRA_LDAP_TRACE_LEVEL")
LDAP_CACERTFILE = os.environ.get("XPRA_LDAP_CACERTFILE")
LDAP_ENCODING = os.environ.get("XPRA_LDAP_ENCODING", "utf-8")


class Authenticator(SysAuthenticatorBase):

    def __init__(self, username, **kwargs):
        self.tls = bool(int(kwargs.pop("tls", "0")))
        self.host = kwargs.pop("host", "localhost")
        self.cacert = kwargs.pop("cacert", LDAP_CACERTFILE)
        self.encoding = kwargs.pop("encoding", LDAP_ENCODING)
        self.uid = parse_uid(kwargs.pop("uid", None))
        self.gid = parse_gid(kwargs.pop("gid", None))
        if self.tls:
            default_port = 636
        else:
            default_port = 389
        self.port = int(kwargs.pop("port", default_port))
        self.username_format = kwargs.pop("username_format", "cn=%username, o=%domain")
        #self.username_format = kwargs.pop("username_format", "%username@%domain")
        SysAuthenticatorBase.__init__(self, username, **kwargs)
        log("ldap auth: host=%s, port=%i, tls=%s, username_format=%s, cacert=%s, encoding=%s",
            self.host, self.port, self.tls, self.username_format, self.cacert, self.encoding)

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
        def emsg(e):
            try:
                log.warn(" LDAP Error: %s", e.message["desc"])
                if "info" in e.message:
                    log.warn("  %s", e.message["info"])
            except:
                #python3: no way to get to the message dict?
                log.warn(" %s", e)
        try:
            import ldap
        except ImportError as e:
            log("check(..)", exc_info=True)
            log.warn("Warning: cannot use ldap authentication:")
            log.warn(" %s", e)
            return False
        try:
            assert self.username and password
            if self.tls:
                protocol = "ldaps"
            else:
                protocol = "ldap"
            server = "%s://%s:%i" % (protocol, self.host, self.port)
            conn = ldap.initialize(server, trace_level=LDAP_TRACE_LEVEL or is_debug_enabled("auth"))
            conn.protocol_version = LDAP_PROTOCOL_VERSION
            conn.set_option(ldap.OPT_REFERRALS, LDAP_REFERRALS)
            if self.cacert:
                conn.set_option(ldap.OPT_X_TLS_CACERTFILE, self.cacert)
            log("ldap.open(%s)=%s", server, conn)
            try:
                domain = socket.getfqdn().split(".", 1)[1]
            except:
                domain = "localdomain"
            user = self.username_format.replace("%username", self.username).replace("%domain", domain)
            log("user=%s", user)
            try:
                #password should be the result of a digest function,
                #ie: xor will return bytes..
                p = bytestostr(password)
                password = p.encode(self.encoding)
                log("ldap encoded password as %s", self.encoding)
            except:
                pass
            v = conn.simple_bind_s(user, password)
            log("simple_bind_s(%s, %s)=%s", user, obsc(password), v)
            return True
        except ldap.INVALID_CREDENTIALS:
            log("check(..)", exc_info=True)
            return False
        except ldap.SERVER_DOWN as e:
            log("check(..)", exc_info=True)
            log.warn("Warning: LDAP %sserver at %s:%i is unreachable", ["", "TLS "][self.tls], self.host, self.port)
            emsg(e)
        except ldap.LDAPError as e:
            log("check(..)", exc_info=True)
            log.warn("Error: ldap authentication failed:")
            emsg(e)
            return False


def main(argv):
    from xpra.util import xor
    from xpra.net.digest import get_salt, get_digests, gendigest
    from xpra.platform import program_context
    with program_context("LDAP-Password-Auth", "LDAP-Password-Authentication"):
        for x in list(argv):
            if x=="-v" or x=="--verbose":
                enable_debug_for("auth")
                argv.remove(x)
        if len(argv) not in (3,4,5,6,7):
            sys.stderr.write("%s invalid arguments\n" % argv[0])
            sys.stderr.write("usage: %s username password [host] [port] [tls] [username_format]\n" % argv[0])
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
        if len(argv)>=7:
            kwargs["username_format"] = argv[6]
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
