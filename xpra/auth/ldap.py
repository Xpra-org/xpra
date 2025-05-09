#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2018 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import sys
import socket
from collections.abc import Sequence

from xpra.util.objects import typedict
from xpra.util.str_fn import obsc, strtobytes
from xpra.util.env import envint
from xpra.util.io import stderr_print
from xpra.auth.sys_auth_base import SysAuthenticatorBase, log
from xpra.auth.common import parse_uid, parse_gid
from xpra.log import is_debug_enabled, consume_verbose_argv

LDAP_REFERRALS = envint("XPRA_LDAP_REFERRALS", 0)
LDAP_PROTOCOL_VERSION = envint("XPRA_LDAP_PROTOCOL_VERSION", 3)
LDAP_TRACE_LEVEL = envint("XPRA_LDAP_TRACE_LEVEL")
LDAP_CACERTFILE = os.environ.get("XPRA_LDAP_CACERTFILE", "")
LDAP_ENCODING = os.environ.get("XPRA_LDAP_ENCODING", "utf-8")
LDAP_USERNAME_FORMAT = os.environ.get("XPRA_LDAP_USERNAME_FORMAT", "cn=%username, o=%domain")


class Authenticator(SysAuthenticatorBase):
    CLIENT_USERNAME = True

    def __init__(self, **kwargs):
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
        self.username_format = kwargs.pop("username_format", LDAP_USERNAME_FORMAT)
        # self.username_format = kwargs.pop("username_format", "%username@%domain")
        super().__init__(**kwargs)
        log("ldap auth: host=%s, port=%i, tls=%s, username_format=%s, cacert=%s, encoding=%s",
            self.host, self.port, self.tls, self.username_format, self.cacert, self.encoding)

    def get_uid(self) -> int:
        return self.uid

    def get_gid(self) -> int:
        return self.gid

    def __repr__(self):
        return "ldap"

    def get_challenge(self, digests: Sequence[str]) -> tuple[bytes, str]:
        if "xor" not in digests:
            log.error("Error: ldap authentication requires the 'xor' digest")
            return b"", ""
        return super().get_challenge(("xor", ))

    def check_password(self, password: str) -> bool:
        log("check_password(%s)", obsc(password))

        def emsg(e):
            try:
                log.warn(" LDAP Error: %s", e.message["desc"])
                if "info" in e.message:
                    log.warn("  %s", e.message["info"])
            except Exception:
                # python3: no way to get to the message dict?
                log.warn(" %s", e)

        try:
            from ldap import (  # pylint: disable=import-outside-toplevel
                initialize, LDAPError,
                INVALID_CREDENTIALS, SERVER_DOWN,
                OPT_REFERRALS,
                OPT_X_TLS_CACERTFILE,
            )
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
            conn = initialize(server, trace_level=LDAP_TRACE_LEVEL or is_debug_enabled("auth"))
            conn.protocol_version = LDAP_PROTOCOL_VERSION
            conn.set_option(OPT_REFERRALS, LDAP_REFERRALS)
            if self.cacert:
                conn.set_option(OPT_X_TLS_CACERTFILE, self.cacert)
            log("ldap.open(%s)=%s", server, conn)
            try:
                domain = socket.getfqdn().split(".", 1)[1]
            except Exception:
                domain = "localdomain"
            user = self.username_format.replace("%username", self.username).replace("%domain", domain)
            log("user=%s", user)
            try:
                pvalue = password.encode(self.encoding)
                log(f"ldap encoded password as {self.encoding}")
            except Exception:
                pvalue = strtobytes(password)
            conn.simple_bind_s(user, pvalue)
            log("simple_bind_s(%s, %s) done", user, obsc(password))
            return True
        except INVALID_CREDENTIALS:
            log("check(..)", exc_info=True)
        except SERVER_DOWN as e:
            log("check(..)", exc_info=True)
            log.warn("Warning: LDAP %sserver at %s:%i is unreachable", ["", "TLS "][self.tls], self.host, self.port)
            emsg(e)
        except LDAPError as e:
            log("check(..)", exc_info=True)
            log.warn("Error: ldap authentication failed:")
            emsg(e)
        return False


def main(argv) -> int:
    # pylint: disable=import-outside-toplevel
    from xpra.net.digest import get_salt, get_digests, gendigest
    from xpra.platform import program_context
    with program_context("LDAP-Password-Auth", "LDAP-Password-Authentication"):
        consume_verbose_argv(argv, "auth")
        if len(argv) not in (3, 4, 5, 6, 7):
            stderr_print("%s invalid arguments" % argv[0])
            stderr_print("usage: %s username password [host] [port] [tls] [username_format]" % argv[0])
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
        if len(argv) >= 7:
            kwargs["username_format"] = argv[6]
        a = Authenticator(**kwargs)
        server_salt, digest = a.get_challenge(("xor", ))
        salt_digest = a.choose_salt_digest(get_digests())
        assert digest == "xor"
        client_salt = get_salt(len(server_salt))
        combined_salt = gendigest(salt_digest, client_salt, server_salt)
        assert digest == "xor"
        response = gendigest(digest, password, combined_salt)
        caps = typedict({
            "challenge_response": response,
            "challenge_client_salt": client_salt,
        })
        r = a.authenticate(caps)
        print("success: %s" % bool(r))
        return int(not r)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
