#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2011 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest

from collections import defaultdict
from xpra.net import net_util
from xpra.net.net_util import (
    get_info, get_interfaces, get_interfaces_addresses,
    get_gateways, get_bind_IPs, do_get_bind_ifacemask,
    get_ssl_info, get_interface,
    get_iface,
)
from unit.test_util import silence_error


class TestVersionUtilModule(unittest.TestCase):

    def test_netifaces(self):
        ifaces = get_interfaces()
        if not ifaces:
            return
        ip_ifaces = defaultdict(list)
        for iface in ifaces:
            ipmasks = do_get_bind_ifacemask(iface)
            for ip, _ in ipmasks:
                ip_ifaces[ip].append(iface)
        for ip, ifaces in ip_ifaces.items():
            assert get_iface(ip) in ifaces, "expected interface for ip %s to be one of %s but got %s" % (
                ip, ifaces, get_iface(ip))
        ia = get_interfaces_addresses()
        assert ia
        #for iface, address in ia.items():
        #    iface2 = get_interface(address)
        #    assert iface2==iface, "expected %s but got %s" % (iface, iface2)
        get_gateways()
        get_bind_IPs()
        get_ssl_info()
        get_info()

        def invalid_iface(s):
            v = get_iface(s)
            if v:
                raise Exception("invalid IP '%s' should not return interface '%s'" % (s, v))
        invalid_iface("")
        invalid_iface("%")
        invalid_iface(":")
        with silence_error(net_util):
            invalid_iface("INVALIDHOSTNAME")
        invalid_iface("10.0.0")
        get_iface("localhost")

        assert not get_interface("invalid")

    def test_ssl_info(self):
        assert get_ssl_info(True)


def main():
    unittest.main()


if __name__ == '__main__':
    main()
