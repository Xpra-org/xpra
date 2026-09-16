#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest
from unittest.mock import patch

from xpra.util.objects import typedict, AdHocStruct
from xpra.net.common import BACKWARDS_COMPATIBLE


class HelloTest(unittest.TestCase):

    def test_display_caps_namespace(self):
        # `display` is both the name of a display subsystem capabilities namespace
        # and the legacy attribute used to carry the display name,
        # the subsystem capabilities must win with modern servers
        from xpra.client.base.client import XpraClientBase
        client = XpraClientBase()
        client.display = ":10"
        display_caps = {"desktop_size": (1024, 768)}
        caps = client._add_common_hello({"display": dict(display_caps)})
        # the display name is always available in the `session` namespace:
        self.assertEqual(caps["session"]["display"], ":10")
        if BACKWARDS_COMPATIBLE:
            self.assertEqual(caps["display"], ":10")
        else:
            self.assertEqual(caps["display"], display_caps)

    def test_legacy_server(self):
        # servers running in backwards compatible mode accept peers older than `MIN_PROTOCOL_VERSION`,
        # and send packets and capabilities which clients using `XPRA_BACKWARDS_COMPATIBLE=0` cannot handle
        from xpra.client.gui import ui_client_base
        from xpra.client.gui.ui_client_base import UIXpraClient
        from xpra.exit_codes import ExitCode
        quit_codes = []
        client = AdHocStruct()
        client._protocol = AdHocStruct()
        client._protocol.TYPE = "xpra"
        client.warn_and_quit = lambda exit_code, _message: quit_codes.append(exit_code)
        legacy_caps = typedict({"protocol-version": (5, 1), "display": ":1"})
        with (
            patch.object(ui_client_base, "BACKWARDS_COMPATIBLE", False),
            patch.object(ui_client_base, "MIN_PROTOCOL_VERSION", (6, 6)),
        ):
            self.assertFalse(UIXpraClient.parse_server_capabilities(client, legacy_caps))
            self.assertEqual(quit_codes, [ExitCode.INCOMPATIBLE_VERSION])
            # the xpra protocol version is irrelevant for VNC servers:
            client._protocol.TYPE = "rfb"
            quit_codes.clear()
            with patch.object(ui_client_base.XpraClientBase, "parse_server_capabilities", return_value=False):
                self.assertFalse(UIXpraClient.parse_server_capabilities(client, legacy_caps))
            self.assertEqual(quit_codes, [])

    def test_no_display(self):
        from xpra.client.base.client import XpraClientBase
        client = XpraClientBase()
        client.display = ""
        caps = client._add_common_hello({})
        self.assertNotIn("display", caps)


def main():
    unittest.main()


if __name__ == '__main__':
    main()
