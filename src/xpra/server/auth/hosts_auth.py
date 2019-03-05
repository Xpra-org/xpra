# This file is part of Xpra.
# Copyright (C) 2017-2018 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import sys

from xpra.os_util import POSIX, strtobytes
from ctypes import CDLL, c_int, c_char_p
from xpra.server.auth.sys_auth_base import SysAuthenticator, init, log
assert init and log #tests will disable logging from here

LIBWRAP = os.environ.get("XPRA_LIBWRAP", "libwrap.so.0")

PRG_NAME = b"xpra"
prg = c_char_p(PRG_NAME)
UNKNOWN = b""
unknown = c_char_p(UNKNOWN)


def check_host(peername, host):
    libwrap = CDLL(LIBWRAP)
    assert libwrap
    hosts_ctl = libwrap.hosts_ctl
    hosts_ctl.argtypes = [c_char_p, c_char_p, c_char_p, c_char_p]
    hosts_ctl.restype = c_int

    log("check_host(%s, %s)", peername, host)
    #name = c_char_p(username)
    c_host = c_char_p(strtobytes(host))
    c_peername = c_char_p(strtobytes(peername))
    #v = hosts_ctl(prg, c_host, unknown, unknown)
    v = hosts_ctl(prg, c_peername, c_host, unknown)
    log("hosts_ctl%s=%s", (PRG_NAME, peername, host, UNKNOWN), v)
    return bool(v)


class Authenticator(SysAuthenticator):

    def __init__(self, username, **kwargs):
        log("hosts.Authenticator(%s, %s)", username, kwargs)
        if not POSIX:
            log.warn("Warning: hosts authentication is not supported on %s", os.name)
            return
        connection = kwargs.get("connection", None)
        try:
            from xpra.net.bytestreams import SocketConnection
            if not connection and isinstance(connection, SocketConnection):
                raise Exception("hosts: invalid connection '%s' (not a socket connection)" % connection)
            info = connection.get_info()
            log("hosts.Authenticator(..) connection info=%s", info)
            host = info.get("remote")[0]
            peername = info.get("endpoint")[0]
        except Exception as e:
            log.error("Error: cannot get host from connection")
            log.error(" %s", e)
            raise
        self.peername = peername
        self.host = host
        SysAuthenticator.__init__(self, username, **kwargs)

    def requires_challenge(self):
        return False

    def authenticate(self, _challenge_response=None, _client_salt=None):
        if not self.host or not check_host(self.peername, self.host):
            errinfo = "'%s'" % self.peername
            if self.peername!=self.host:
                errinfo += " ('%s')" % self.host
            log.warn("Warning: access denied for host %s" % errinfo)
            return False
        return True

    def __repr__(self):
        return "hosts"


def main():
    from xpra.platform import program_context
    with program_context("Host Check", "Host Check"):
        for x in ("-v", "--verbose"):
            while x in sys.argv:
                sys.argv.remove(x)
                log.enable_debug()
        if len(sys.argv)<3:
            print("usage: %s peername1 hostname1 [peername2 hostname2] [..]" % sys.argv[0])
            return 1
        sys.argv = sys.argv[1:]
        while len(sys.argv)>=2:
            peername, host = sys.argv[:2]
            check = check_host(peername, host)
            print("host check for '%s', '%s': %s" % (peername, host, check))
            sys.argv = sys.argv[2:]
    return 0

if __name__ == "__main__":
    v= main()
    sys.exit(v)
