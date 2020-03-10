#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2011-2020 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest

from xpra.net.net_util import (
    get_info, get_interfaces, get_interfaces_addresses, #get_interface,
    get_gateways, get_bind_IPs, do_get_bind_ifacemask,
    get_ssl_info,
    )


class TestVersionUtilModule(unittest.TestCase):

    def test_netifaces(self):
        ifaces = get_interfaces()
        if not ifaces:
            return
        for iface in ifaces:
            do_get_bind_ifacemask(iface)
        ia = get_interfaces_addresses()
        assert ia
        #for iface, address in ia.items():
        #    iface2 = get_interface(address)
        #    assert iface2==iface, "expected %s but got %s" % (iface, iface2)
        get_gateways()
        get_bind_IPs()
        get_ssl_info()
        get_info()


def main():
    unittest.main()

if __name__ == '__main__':
    main()
