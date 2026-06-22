#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from xpra.server.subsystem.mdns import MdnsServer


class TestMdnsServer(unittest.TestCase):

    def test_get_mdns_info_includes_extra_info(self):
        server = SimpleNamespace(
            session_type="seamless",
            session_name="test-session",
            subsystems={"id": SimpleNamespace(uuid="uuid-1")},
        )
        mdns = MdnsServer(server)
        mdns.extra_info["vsock"] = "7:10000"

        with patch("xpra.server.subsystem.mdns.get_username", return_value="user"):
            info = mdns.get_mdns_info()

        self.assertEqual(info["vsock"], "7:10000")
        self.assertEqual(info["uuid"], "uuid-1")


def main():
    unittest.main()


if __name__ == "__main__":
    main()
