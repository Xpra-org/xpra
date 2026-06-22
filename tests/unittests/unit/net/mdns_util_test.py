#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys
import unittest
from types import ModuleType
from unittest.mock import patch

from xpra.net.mdns.util import mdns_publish


class FakeZeroconfMulticast:
    instances = []

    def __init__(self, listen_on, service_name, service_type, text_dict):
        self.listen_on = listen_on
        self.service_name = service_name
        self.service_type = service_type
        self.text_dict = text_dict
        FakeZeroconfMulticast.instances.append(self)


class TestMdnsUtil(unittest.TestCase):

    def setUp(self):
        FakeZeroconfMulticast.instances = []

    def test_uuid_makes_service_name_unique(self):
        publisher_module = ModuleType("xpra.net.mdns.zeroconf_publisher")
        publisher_module.get_interface_index = lambda host: host
        publisher_module.ZeroconfMulticast = FakeZeroconfMulticast
        with patch("xpra.net.mdns.util.socket.gethostname", return_value="host"), \
                patch.dict(sys.modules, {"xpra.net.mdns.zeroconf_publisher": publisher_module}):
            mdns_publish("", (("192.0.2.1", 22),), {"mode": "ssh", "uuid": "abcdef123456"})
            mdns_publish("", (("192.0.2.1", 22),), {"mode": "ssh", "uuid": "123456789abc"})

        names = [publisher.service_name for publisher in FakeZeroconfMulticast.instances]
        self.assertEqual(names, ["host abcdef123456 (ssh)", "host 123456789abc (ssh)"])


def main():
    unittest.main()


if __name__ == "__main__":
    main()
