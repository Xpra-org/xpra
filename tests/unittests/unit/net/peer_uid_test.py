#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import socket
import tempfile
import unittest

from xpra.os_util import LINUX, POSIX
from xpra.net.common import get_peer_uid, proc_net_addr, proc_net_addr_keys


def has_ipv6(host="::1") -> bool:
    """
        `socket.has_ipv6` only tells us that Python was built with IPv6 support,
        it does not tell us that this host can bind `host`:
        kernels booted with `ipv6.disable=1` cannot even create an IPv6 socket,
        and hosts with `net.ipv6.conf.all.disable_ipv6=1` can create one
        but have no address left to bind it to.
    """
    if not socket.has_ipv6:
        return False
    try:
        sock = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
    except OSError:
        return False
    try:
        sock.bind((host, 0))
    except OSError:
        return False
    finally:
        sock.close()
    return True


class TestPeerUID(unittest.TestCase):

    def test_has_ipv6_unassigned_address(self):
        # the probe must bind and not just create a socket:
        # this RFC 3849 documentation address is never assigned to a local interface
        assert not has_ipv6("2001:db8::1")

    def test_proc_net_addr(self):
        # the 32 bit words are in host byte order, the port is not:
        assert proc_net_addr(socket.AF_INET, ("127.0.0.1", 8080)) == "0100007F:1F90"
        assert proc_net_addr(socket.AF_INET, ("0.0.0.0", 0)) == "00000000:0000"
        assert proc_net_addr(socket.AF_INET6, ("::1", 8080)) == "00000000000000000000000001000000:1F90"
        # the scope id must be stripped:
        assert proc_net_addr(socket.AF_INET6, ("::1%lo", 1)) == proc_net_addr(socket.AF_INET6, ("::1", 1))

    def test_proc_net_addr_keys(self):
        # an IPv4 address can also be found in the IPv6 file, as a v4 mapped address:
        v4, v6 = proc_net_addr_keys(("127.0.0.1", 8080))
        assert v4 == "0100007F:1F90"
        assert v6 == proc_net_addr(socket.AF_INET6, ("::ffff:127.0.0.1", 8080))
        # a real IPv6 address can only be found in the IPv6 file:
        v4, v6 = proc_net_addr_keys(("::1", 8080))
        assert not v4
        assert v6
        # a v4 mapped address can be found in either:
        v4, v6 = proc_net_addr_keys(("::ffff:127.0.0.1", 8080))
        assert v4 == "0100007F:1F90"
        assert v6

    def connect_pair(self, family, address, client_family=0, client_host=""):
        server = socket.socket(family, socket.SOCK_STREAM)
        self.addCleanup(server.close)
        server.bind(address)
        server.listen(1)
        port = server.getsockname()[1]
        client = socket.socket(client_family or family, socket.SOCK_STREAM)
        self.addCleanup(client.close)
        client.connect((client_host or address[0], port))
        conn, _ = server.accept()
        self.addCleanup(conn.close)
        return conn, client

    def test_local_tcp(self):
        if not LINUX:
            return
        uid = os.getuid()
        for family, address in (
            (socket.AF_INET, ("127.0.0.1", 0)),
            (socket.AF_INET6, ("::1", 0)),
        ):
            with self.subTest(family=family):
                if family == socket.AF_INET6 and not has_ipv6():
                    self.skipTest("no IPv6 support on this host")
                conn, client = self.connect_pair(family, address)
                # both ends of a local connection can identify each other:
                assert get_peer_uid(conn) == uid, f"expected uid {uid} for {family}"
                assert get_peer_uid(client) == uid, f"expected uid {uid} for {family}"

    def test_local_tcp_v4mapped(self):
        if not LINUX:
            return
        # this test only needs the wildcard address, which is still bindable
        # on hosts where `::1` has been removed from the loopback interface:
        if not has_ipv6("::"):
            self.skipTest("no IPv6 support on this host")
        # an IPv4 client connecting to an IPv6 socket:
        conn, client = self.connect_pair(socket.AF_INET6, ("::", 0), socket.AF_INET, "127.0.0.1")
        uid = os.getuid()
        assert get_peer_uid(conn) == uid
        assert get_peer_uid(client) == uid

    def test_listen_socket(self):
        # a socket which is not connected has no peer:
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.addCleanup(server.close)
        server.bind(("127.0.0.1", 0))
        server.listen(1)
        assert get_peer_uid(server) == -1

    def test_unix_socket(self):
        if not POSIX:
            return
        tmpdir = tempfile.mkdtemp()
        sockpath = os.path.join(tmpdir, "test-socket")
        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.addCleanup(server.close)
        server.bind(sockpath)
        server.listen(1)
        client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.addCleanup(client.close)
        client.connect(sockpath)
        conn, _ = server.accept()
        self.addCleanup(conn.close)
        assert get_peer_uid(conn) == os.getuid()
        os.unlink(sockpath)
        os.rmdir(tmpdir)

    def test_no_socket(self):
        assert get_peer_uid(None) == -1
        assert get_peer_uid(object()) == -1


def main():
    unittest.main()


if __name__ == '__main__':
    main()
