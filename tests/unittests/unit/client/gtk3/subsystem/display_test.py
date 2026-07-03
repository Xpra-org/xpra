#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest

from unit.process_test_util import DisplayContext


class Gtk3DisplayClientTest(unittest.TestCase):
    """
    Real end-to-end check that a concrete `xpra.client.gtk3.client.XpraClient()`
    actually composes a `Gtk3DisplayClient` for its `display` subsystem (via
    `GTKXpraClient.get_subsystem_classes()`), and that the toolkit-specific
    implementation returns real values instead of the base class'
    `NotImplementedError` stubs.
    """

    def test_gtk3_display_client(self):
        with DisplayContext():
            from xpra.client.gtk3.client import XpraClient
            from xpra.client.gtk3.subsystem.display import Gtk3DisplayClient
            client = XpraClient()
            try:
                display = client.get_subsystem("display")
                self.assertIsNotNone(display, "no `display` subsystem composed")
                self.assertIsInstance(display, Gtk3DisplayClient)

                root_w, root_h = display.get_root_size()
                self.assertGreater(root_w, 0)
                self.assertGreater(root_h, 0)

                sizes = display.get_screen_sizes()
                self.assertTrue(sizes)

                monitors = display.get_monitors_info()
                self.assertIsInstance(monitors, dict)

                self.assertIsInstance(display.has_transparency(), bool)
            finally:
                client.cleanup()


def main():
    unittest.main()


if __name__ == '__main__':
    main()
