#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest

from xpra.server.source.display import DisplayConnection, MAX_DESKTOP_NAMES, MAX_DESKTOP_NAME
from xpra.util.objects import typedict


def make_icc_profile(size: int = 128) -> bytes:
    profile = bytearray(size)
    profile[:4] = size.to_bytes(4, "big")
    profile[36:40] = b"acsp"
    return bytes(profile)


class DisplayConnectionTest(unittest.TestCase):

    def test_desktop_names_are_cleaned(self):
        dc = DisplayConnection()
        dc.init_state()
        # a NUL would split the `_NET_DESKTOP_NAMES` list:
        dc.set_desktops(3, ("one\0two", "line1\nline2‮", "x" * 1000))
        self.assertEqual(dc.desktops, 3)
        self.assertEqual(dc.desktop_names[:2], ("onetwo", "line1 line2"))
        self.assertEqual(len(dc.desktop_names[2]), MAX_DESKTOP_NAME)

    def test_desktop_names_are_limited(self):
        dc = DisplayConnection()
        dc.init_state()
        dc.set_desktops(1000, tuple(str(i) for i in range(1000)))
        self.assertEqual(len(dc.desktop_names), MAX_DESKTOP_NAMES)

    def test_icc_capabilities_are_validated(self):
        dc = DisplayConnection()
        dc.init_state()
        profile = make_icc_profile()
        dc.parse_client_caps(typedict({"display": {
            "icc": {"data": bytearray(profile)},
            "display-icc": {0: {"data": profile}},
        }}))
        self.assertEqual(dc.icc["data"], profile)
        self.assertIsInstance(dc.icc["data"], bytes)
        self.assertEqual(dc.display_icc[0]["data"], profile)

        with self.assertRaises(ValueError):
            dc.parse_client_caps(typedict({"display": {"icc": {"data": b"invalid"}}}))


def main():
    unittest.main()


if __name__ == "__main__":
    main()
