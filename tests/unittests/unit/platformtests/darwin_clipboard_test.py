#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

"""
Tests for the MacOS clipboard helper, and in particular for the multiple pasteboard formats
which can be exchanged with the peer.
All the tests use a private pasteboard, so the user's clipboard is never modified.
All tests are skipped on non-MacOS platforms.
"""

import sys
import unittest
from io import BytesIO

OSX = sys.platform == "darwin"


def make_png(size=(32, 32)) -> bytes:
    from PIL import Image
    buf = BytesIO()
    Image.new("RGBA", size, (255, 0, 0, 128)).save(buf, "png")
    return buf.getvalue()


def make_test_class():
    from AppKit import NSPasteboard
    from xpra.platform.darwin.ctypes_clipboard import OSXClipboardProtocolHelper

    class TestClipboard(OSXClipboardProtocolHelper):
        # never touch the user's clipboard:
        @staticmethod
        def get_pasteboard():
            return NSPasteboard.pasteboardWithUniqueName()

        def cleanup(self) -> None:
            pasteboard = self.pasteboard
            super().cleanup()
            if pasteboard:
                pasteboard.releaseGlobally()

    return TestClipboard


@unittest.skipUnless(OSX, "the pasteboard is only available on MacOS")
class DarwinClipboardTest(unittest.TestCase):

    def make_helper(self, all_selections=False):
        packets = []
        kwargs = {"all-selections": all_selections}
        helper = make_test_class()(lambda *packet: packets.append(packet), **kwargs)
        self.addCleanup(helper.cleanup)
        helper.enable_selections(helper._clipboard_proxies.keys())
        return helper, packets

    def make_proxy(self):
        helper, packets = self.make_helper()
        proxy = helper._clipboard_proxies["CLIPBOARD"]
        proxy.set_direction(True, True)
        return proxy, packets

    def test_target_mapping(self):
        from xpra.platform.darwin.ctypes_clipboard import pasteboard_targets, select_targets
        targets = pasteboard_targets(("public.utf8-plain-text", "public.html", "com.adobe.pdf"))
        self.assertIn("UTF8_STRING", targets)
        self.assertIn("text/html", targets)
        self.assertIn("application/pdf", targets)
        # native pasteboard types must never be exposed to the peer:
        for nstype in ("com.apple.traditional-mac-plain-text", "dyn.ah62d", "NeXT TIFF v4.0 pasteboard type"):
            self.assertNotIn(nstype, pasteboard_targets((nstype, )))
        # we can convert to any image format, no matter which one the pasteboard holds:
        image_targets = pasteboard_targets(("public.tiff", ))
        self.assertIn("image/png", image_targets)
        self.assertIn("image/tiff", image_targets)
        # we only request one target per pasteboard format:
        offered = ("UTF8_STRING", "text/plain", "text/html", "image/png", "image/tiff")
        self.assertEqual(select_targets(offered), ("UTF8_STRING", "text/html", "image/png"))
        # and never the formats we already have:
        self.assertEqual(select_targets(offered, have=("STRING", "image/tiff")), ("text/html", ))

    def test_uri_types(self):
        from xpra.platform.darwin.ctypes_clipboard import parse_uri_list, uri_types
        uris = parse_uri_list(b"# a comment\r\nhttps://xpra.org/\r\n")
        self.assertEqual(uris, ("https://xpra.org/", ))
        self.assertEqual(uri_types(uris), {"public.url": "https://xpra.org/"})
        # a remote path which does not exist here must not be exposed as a file:
        self.assertEqual(uri_types(("file:///no-such-path-here-1234", )), {})

    def test_token_sets_all_the_formats(self):
        proxy, _ = self.make_proxy()
        png = make_png()
        proxy.got_token((), {
            "UTF8_STRING": ("UTF8_STRING", 8, b"hello"),
            "text/html": ("text/html", 8, b"<b>hello</b>"),
            "text/uri-list": ("text/uri-list", 8, b"https://xpra.org/\r\n"),
            "text/rtf": ("text/rtf", 8, rb"{\rtf1\ansi hello}"),
            "application/pdf": ("application/pdf", 8, b"%PDF-1.4 not really a pdf"),
            "image/png": ("image/png", 8, png),
        })
        pasteboard = proxy.pasteboard
        self.assertEqual(pasteboard.stringForType_("public.utf8-plain-text"), "hello")
        self.assertEqual(pasteboard.stringForType_("public.html"), "<b>hello</b>")
        self.assertEqual(pasteboard.stringForType_("public.url"), "https://xpra.org/")
        for nstype in ("public.rtf", "com.adobe.pdf", "public.png", "public.tiff"):
            self.assertTrue(pasteboard.dataForType_(nstype), f"no {nstype!r} data")
        # and we can send them all back:
        targets = proxy.get_targets()
        for target in ("UTF8_STRING", "text/html", "text/uri-list", "text/rtf", "application/pdf",
                       "image/png", "image/tiff"):
            self.assertIn(target, targets)
            values = []
            proxy.get_contents(target, lambda *args: values.append(args))
            self.assertTrue(values[0][2], f"no data for {target!r}")

    def test_invalid_data_is_dropped(self):
        proxy, _ = self.make_proxy()
        proxy.got_token((), {
            "UTF8_STRING": ("UTF8_STRING", 8, b"hello"),
            "application/pdf": ("application/pdf", 8, b"this is not a pdf"),
            "image/png": ("image/png", 8, b"this is not an image"),
        })
        pasteboard = proxy.pasteboard
        self.assertEqual(pasteboard.stringForType_("public.utf8-plain-text"), "hello")
        self.assertFalse(pasteboard.dataForType_("com.adobe.pdf"))
        self.assertFalse(pasteboard.dataForType_("public.png"))
        # a truncated image has a valid header, but cannot be loaded:
        proxy.got_token((), {
            "UTF8_STRING": ("UTF8_STRING", 8, b"text survives"),
            "image/png": ("image/png", 8, make_png()[:64]),
        })
        self.assertEqual(pasteboard.stringForType_("public.utf8-plain-text"), "text survives")
        self.assertFalse(pasteboard.dataForType_("public.png"))

    def test_unknown_target(self):
        proxy, _ = self.make_proxy()
        values = []
        proxy.get_contents("application/x-made-up", lambda *args: values.append(args))
        self.assertEqual(values, [("application/x-made-up", 8, b"")])

    def test_contents_are_merged(self):
        # the replies to separate requests must not clobber each other:
        proxy, _ = self.make_proxy()
        proxy.got_contents("UTF8_STRING", "UTF8_STRING", 8, b"hello")
        proxy.got_contents("image/png", "image/png", 8, make_png())
        pasteboard = proxy.pasteboard
        self.assertEqual(pasteboard.stringForType_("public.utf8-plain-text"), "hello")
        self.assertTrue(pasteboard.dataForType_("public.png"))

    def requested_targets(self, packets) -> tuple[str, ...]:
        return tuple(packet[3] for packet in packets if packet[0] == "clipboard-request")

    def test_targets_are_requested(self):
        proxy, packets = self.make_proxy()
        proxy.got_token(("UTF8_STRING", "text/html", "image/png", "image/tiff", "custom"))
        self.assertEqual(self.requested_targets(packets), ("UTF8_STRING", "text/html", "image/png"))

    def test_missing_formats_are_requested(self):
        # the legacy packet format can only carry one target,
        # the others must be requested:
        proxy, packets = self.make_proxy()
        proxy.got_token(("UTF8_STRING", "text/html", "image/png"), {
            "UTF8_STRING": ("UTF8_STRING", 8, b"hello"),
        })
        self.assertEqual(self.requested_targets(packets), ("text/html", "image/png"))
        self.assertEqual(proxy.pasteboard.stringForType_("public.utf8-plain-text"), "hello")

    def test_greedy_token_carries_multiple_formats(self):
        proxy, _ = self.make_proxy()
        proxy.got_token((), {
            "UTF8_STRING": ("UTF8_STRING", 8, b"hello"),
            "text/html": ("text/html", 8, b"<b>hello</b>"),
        })
        # (the legacy packet format can only carry one of them,
        # so we validate the token data before it is encoded)
        tokens = []
        proxy.send_clipboard_token_handler = lambda proxy, token_data: tokens.append(token_data)
        proxy._greedy_client = True
        proxy._want_targets = True
        proxy.set_preferred_targets(("UTF8_STRING", "text/html"))
        proxy.do_emit_token()
        self.assertEqual(len(tokens), 1)
        self.assertEqual(set(tokens[0]["data"].keys()), {"UTF8_STRING", "text/html"})
        self.assertIn("text/html", tokens[0]["targets"])

    def test_preferred_targets(self):
        helper, _ = self.make_helper()
        preferred = helper.get_caps()["preferred-targets"]
        for target in ("UTF8_STRING", "text/html", "text/uri-list", "image/png", "application/pdf"):
            self.assertIn(target, preferred)


def main():
    unittest.main()


if __name__ == "__main__":
    main()
