#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest

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
