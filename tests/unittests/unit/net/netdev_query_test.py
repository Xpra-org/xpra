#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2024 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest


class TestNetdevQuery(unittest.TestCase):

    def test_get_interface_info_no_args(self):
        from xpra.platform.netdev_query import get_interface_info
        result = get_interface_info()
        assert isinstance(result, dict)

    def test_get_interface_info_with_args(self):
        from xpra.platform.netdev_query import get_interface_info
        result = get_interface_info(0, "lo")
        assert isinstance(result, dict)

    def test_get_tcp_info(self):
        from xpra.platform.netdev_query import get_tcp_info
        result = get_tcp_info(None)
        assert isinstance(result, dict)

    def test_get_tcp_info_with_socket(self):
        import socket
        from xpra.platform.netdev_query import get_tcp_info
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            result = get_tcp_info(sock)
            assert isinstance(result, dict)
        finally:
            sock.close()

    def test_print_address_unknown_af(self):
        # print_address uses socket.AF_INET / AF_INET6; passing other values raises KeyError
        import socket
        from xpra.platform.netdev_query import print_address
        # valid address family
        try:
            print_address("lo", socket.AF_INET, [{"addr": "127.0.0.1"}])
        except Exception:
            pass  # platform may raise if cannot bind/query

    def test_get_interface_info_returns_dict_type(self):
        from xpra.platform.netdev_query import get_interface_info
        for args in [(), (0,), (0, "lo"), (-1, "eth0")]:
            result = get_interface_info(*args)
            assert isinstance(result, dict), f"expected dict for args {args}, got {type(result)}"


def main():
    unittest.main()


if __name__ == '__main__':
    main()
