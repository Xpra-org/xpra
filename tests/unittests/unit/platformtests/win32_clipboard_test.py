#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

"""
Tests for the win32 clipboard helper, and in particular for the `PRIMARY` selection
which is enabled with `--clipboard=all` (the default on Windows).
All tests are skipped on non-Windows platforms.
"""

import sys
import unittest

from xpra.net.common import Packet

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


def flush() -> None:
    # run the pending `GLib.idle_add` callbacks
    from xpra.os_util import gi_import
    context = gi_import("GLib").MainContext.default()
    for _ in range(100):
        if not context.pending():
            break
        context.iteration(False)


@unittest.skipUnless(WIN32, "the win32 clipboard is only available on MS Windows")
class Win32ClipboardTest(unittest.TestCase):

    def make_helper(self, all_selections=True):
        packets = []
        kwargs = {"all-selections": all_selections}
        helper = make_test_class()(lambda *packet: packets.append(packet), **kwargs)
        self.addCleanup(helper.cleanup)
        helper.enable_selections(helper._clipboard_proxies.keys())
        return helper, packets

    def test_default_selections(self):
        helper, _ = self.make_helper(all_selections=False)
        self.assertEqual(tuple(helper._clipboard_proxies.keys()), ("CLIPBOARD",))
        self.assertIsNone(helper.primary_proxy)

    def test_all_selections(self):
        helper, _ = self.make_helper()
        self.assertEqual(tuple(helper._clipboard_proxies.keys()), ("CLIPBOARD", "PRIMARY"))
        self.assertEqual(helper.get_caps()["selections"], ("CLIPBOARD", "PRIMARY"))
        # `PRIMARY` must not be greedy: we don't want the data with every token
        self.assertEqual(helper.local_greedy, ("CLIPBOARD",))
        self.assertEqual(helper.get_caps()["greedy"], ("CLIPBOARD",))
        preferred = helper.get_caps()["preferred-targets"]
        self.assertIn("image/webp", preferred)
        self.assertIn("image/bmp", preferred)
        self.assertNotIn("image/tiff", preferred)

    def test_primary_is_receive_only(self):
        helper, packets = self.make_helper()
        primary = helper.primary_proxy
        self.assertFalse(primary._can_send)
        self.assertTrue(primary._can_receive)
        # even if the direction changes:
        helper.set_direction(True, True)
        self.assertFalse(primary._can_send)
        # we never claim the selection:
        helper.send_all_tokens()
        self.assertNotIn("PRIMARY", tuple(packet[1] for packet in packets))

    def test_primary_token_schedules_request(self):
        helper, packets = self.make_helper()
        primary = helper.primary_proxy
        helper.process_clipboard_packet(Packet("clipboard-data", "PRIMARY", {}))
        # the request must be delayed:
        self.assertTrue(primary.request_timer)
        self.assertEqual(packets, [])
        # a second token does not schedule a second request:
        timer = primary.request_timer
        helper.process_clipboard_packet(Packet("clipboard-data", "PRIMARY", {}))
        self.assertEqual(primary.request_timer, timer)
        # fire the timer:
        primary.request_contents()
        self.assertEqual(len(packets), 1)
        packet_type, _, selection, target = packets[0]
        self.assertEqual((packet_type, selection, target), ("clipboard-request", "PRIMARY", "UTF8_STRING"))

    def test_clipboard_token_cancels_primary_request(self):
        helper, _ = self.make_helper()
        primary = helper.primary_proxy
        primary.schedule_request()
        self.assertTrue(primary.request_timer)
        # a real copy takes precedence over a mouse selection:
        helper.process_clipboard_packet(Packet("clipboard-data", "CLIPBOARD", {}))
        self.assertFalse(primary.request_timer)

    def test_local_clipboard_change_cancels_primary_request(self):
        from xpra.platform.win32 import ctypes_clipboard
        helper, _ = self.make_helper()
        primary = helper.primary_proxy
        primary.schedule_request()
        emitted = []
        for selection, proxy in helper._clipboard_proxies.items():
            proxy.schedule_emit_token = lambda min_delay=0, selection=selection: emitted.append(selection)
        # pretend another application has taken ownership of the local clipboard:
        owner = ctypes_clipboard.GetClipboardOwner
        self.addCleanup(setattr, ctypes_clipboard, "GetClipboardOwner", owner)
        ctypes_clipboard.GetClipboardOwner = lambda: 0xBADF00D
        helper.wnd_proc(0, ctypes_clipboard.WM_CLIPBOARDUPDATE, 0, 0)
        self.assertFalse(primary.request_timer)
        # and we only tell the peer about the selections we can send:
        self.assertEqual(emitted, ["CLIPBOARD"])

    def test_primary_contents_saved_to_clipboard(self):
        helper, packets = self.make_helper()
        primary = helper.primary_proxy
        texts = []
        helper._clipboard_proxies["CLIPBOARD"].set_clipboard_text = texts.append
        primary.got_contents("UTF8_STRING", "UTF8_STRING", 8, b"hello")
        self.assertEqual(texts, ["hello"])
        # we must not have claimed anything:
        self.assertEqual(packets, [])
        # anything that is not text is ignored:
        primary.got_contents("UTF8_STRING", "", 8, b"")
        primary.got_contents("image/png", "image/png", 8, b"not text")
        self.assertEqual(texts, ["hello"])

    def use_new_packet_format(self):
        # only the 6.5+ packet format can carry more than one clipboard format:
        from xpra.clipboard import core
        self.addCleanup(setattr, core, "BACKWARDS_COMPATIBLE", core.BACKWARDS_COMPATIBLE)
        core.BACKWARDS_COMPATIBLE = False

    def test_non_greedy_token_does_not_touch_the_clipboard(self):
        # the common case: the peer is not greedy, so it gets a bare token
        # and requests whatever it needs later
        self.use_new_packet_format()
        helper, packets = self.make_helper()
        proxy = helper._clipboard_proxies["CLIPBOARD"]
        self.assertFalse(proxy._greedy_client)

        def fail(*_args, **_kwargs):
            raise AssertionError("the clipboard must not be opened for a non-greedy peer")

        proxy.with_clipboard_lock = fail
        proxy.do_emit_token()
        flush()
        self.assertEqual(len(packets), 1)
        packet_type, selection, options = packets[0]
        self.assertEqual((packet_type, selection), ("clipboard-data", "CLIPBOARD"))
        self.assertNotIn("targets", options)
        self.assertNotIn("data", options)

    def make_greedy_proxy(self, formats, contents, sequence=(1, 1)):
        from xpra.platform.win32 import ctypes_clipboard
        self.use_new_packet_format()
        helper, packets = self.make_helper()
        proxy = helper._clipboard_proxies["CLIPBOARD"]
        proxy._greedy_client = True
        # never touch the real clipboard:
        proxy.with_clipboard_lock = lambda success, _failure, **_kwargs: success()
        self.addCleanup(setattr, ctypes_clipboard, "get_clipboard_formats",
                        ctypes_clipboard.get_clipboard_formats)
        ctypes_clipboard.get_clipboard_formats = lambda: formats
        numbers = list(sequence)
        self.addCleanup(setattr, ctypes_clipboard, "GetClipboardSequenceNumber",
                        ctypes_clipboard.GetClipboardSequenceNumber)
        ctypes_clipboard.GetClipboardSequenceNumber = lambda: numbers.pop(0) if len(numbers) > 1 else numbers[0]
        collected = []

        def get_contents(target, callback):
            collected.append(target)
            callback(target, 8, contents.get(target, b""))

        proxy.get_contents = get_contents
        return helper, packets, proxy, collected

    def clipboard_formats(self):
        from xpra.platform.win32 import win32con
        from xpra.platform.win32.common import LPCSTR, RegisterClipboardFormatA
        html = RegisterClipboardFormatA(LPCSTR(b"HTML Format\0"))
        self.assertTrue(html)
        return (win32con.CF_UNICODETEXT, win32con.CF_TEXT, win32con.CF_DIBV5, html)

    def test_greedy_token_sends_one_target_per_format(self):
        contents = {
            "UTF8_STRING": b"some text",
            "text/html": b"<b>some html</b>",
            "image/png": b"fake png",
        }
        _, packets, proxy, collected = self.make_greedy_proxy(self.clipboard_formats(), contents)
        proxy.do_emit_token()
        flush()
        self.assertEqual(len(packets), 1)
        packet_type, selection, options = packets[0]
        self.assertEqual((packet_type, selection), ("clipboard-data", "CLIPBOARD"))
        # one target per clipboard format, most descriptive first:
        self.assertEqual(collected, ["UTF8_STRING", "text/html", "image/png"])
        self.assertEqual(tuple(options["data"].keys()), ("UTF8_STRING", "text/html", "image/png"))
        for target, data in contents.items():
            self.assertEqual(options["data"][target], (target, 8, "bytes", data))
        # the aliases are still advertised, their data is just not duplicated:
        for alias in ("text/plain", "TEXT", "STRING", "image/jpeg", "image/webp", "image/bmp"):
            self.assertIn(alias, options["targets"])
            self.assertNotIn(alias, options["data"])

    def test_greedy_token_dropped_when_the_clipboard_changes(self):
        contents = {"UTF8_STRING": b"some text"}
        _, packets, proxy, _ = self.make_greedy_proxy(self.clipboard_formats(), contents,
                                                      sequence=(1, 2))
        proxy.do_emit_token()
        flush()
        # the contents would have been a mix of two different clipboard owners:
        self.assertEqual(packets, [])

    def test_greedy_token_with_no_usable_formats(self):
        from xpra.platform.win32 import win32con
        _, packets, proxy, collected = self.make_greedy_proxy((win32con.CF_ENHMETAFILE,), {})
        proxy.do_emit_token()
        flush()
        self.assertEqual(collected, [])
        self.assertEqual(len(packets), 1)
        _, _, options = packets[0]
        self.assertNotIn("data", options)

    def test_image_target_without_data_is_requested(self):
        for image_target in ("image/png", "image/webp", "image/bmp"):
            with self.subTest(image_target=image_target):
                helper, packets = self.make_helper()
                options = {"targets": ("UTF8_STRING", image_target)}
                helper.process_clipboard_packet(Packet("clipboard-data", "CLIPBOARD", options))
                self.assertEqual(len(packets), 1)
                packet_type, _, selection, target = packets[0]
                self.assertEqual(
                    (packet_type, selection, target),
                    ("clipboard-request", "CLIPBOARD", image_target),
                )

    def test_image_sent_with_the_token_is_not_requested_again(self):
        helper, packets = self.make_helper()
        proxy = helper._clipboard_proxies["CLIPBOARD"]
        images = []
        proxy.set_clipboard_image = lambda img_format, data: images.append((img_format, data))
        options = {
            "targets": ("UTF8_STRING", "image/png"),
            "data": {"image/png": ("image/png", 8, "bytes", b"fake png")},
        }
        helper.process_clipboard_packet(Packet("clipboard-data", "CLIPBOARD", options))
        # we already have the image, so we must not ask for it again:
        self.assertEqual(packets, [])
        self.assertEqual(images, [("png", b"fake png")])

    def test_primary_token_with_data(self):
        helper, _ = self.make_helper()
        primary = helper.primary_proxy
        texts = []
        helper._clipboard_proxies["CLIPBOARD"].set_clipboard_text = texts.append
        primary.schedule_request()
        options = {
            "data": {"UTF8_STRING": ("UTF8_STRING", 8, "bytes", b"hello")},
        }
        helper.process_clipboard_packet(Packet("clipboard-data", "PRIMARY", options))
        # no need to request anything, we already have the data:
        self.assertFalse(primary.request_timer)
        self.assertEqual(texts, ["hello"])


def main():
    unittest.main()


if __name__ == "__main__":
    main()
