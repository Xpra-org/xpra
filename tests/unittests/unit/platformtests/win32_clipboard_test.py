#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

"""Tests for the win32 clipboard helper. Skipped on non-Windows platforms."""

import sys
import unittest

WIN32 = sys.platform == "win32"


def make_test_class():
    from xpra.platform.win32.ctypes_clipboard import Win32Clipboard

    class TestClipboard(Win32Clipboard):
        # these tests never touch the OS clipboard,
        # so we can do without the message window:
        def init_window(self) -> None:
            self.wndclass = None
            self.wndclass_handle = 0
            self.window = 0

    return TestClipboard


@unittest.skipUnless(WIN32, "the win32 clipboard is only available on MS Windows")
class Win32ClipboardTest(unittest.TestCase):

    def make_helper(self):
        packets = []
        helper = make_test_class()(lambda *packet: packets.append(packet))
        self.addCleanup(helper.cleanup)
        helper.enable_selections(helper._clipboard_proxies.keys())
        return helper, packets

    def test_image_target_without_data_is_requested(self):
        helper, packets = self.make_helper()
        proxy = helper._clipboard_proxies["CLIPBOARD"]
        proxy.got_token(("UTF8_STRING", "image/png"))
        self.assertEqual(len(packets), 1)
        packet_type, _, selection, target = packets[0]
        self.assertEqual((packet_type, selection, target), ("clipboard-request", "CLIPBOARD", "image/png"))

    def test_image_sent_with_the_token_is_not_requested_again(self):
        helper, packets = self.make_helper()
        proxy = helper._clipboard_proxies["CLIPBOARD"]
        images = []
        proxy.set_clipboard_image = lambda img_format, data: images.append((img_format, data))
        targets = ("UTF8_STRING", "image/png")
        target_data = {"image/png": ("image/png", 8, b"fake png")}
        proxy.got_token(targets, target_data)
        # we already have the image, so we must not ask for it again:
        self.assertEqual(packets, [])
        self.assertEqual(images, [("png", b"fake png")])


def main():
    unittest.main()


if __name__ == "__main__":
    main()
