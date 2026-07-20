#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest

from xpra.net.common import Packet
from xpra.clipboard import core
from xpra.clipboard.common import ALL_CLIPBOARDS, parse_greedy
from xpra.clipboard.core import ClipboardProtocolHelperCore
from xpra.util.objects import typedict


class ClipboardProxy:
    def __init__(self, selection: str):
        self._selection = selection
        self._can_send = True
        self._can_receive = True
        self._greedy_client = False
        self.tokens = []

    @staticmethod
    def is_enabled() -> bool:
        return True

    def got_token(self, targets, target_data, claim, synchronous_client) -> None:
        self.tokens.append((targets, target_data, claim, synchronous_client))

    def set_greedy_client(self, greedy: bool) -> None:
        self._greedy_client = greedy


class ClipboardHelper(ClipboardProtocolHelperCore):
    def make_proxy(self, selection: str):
        return ClipboardProxy(selection)


class ClipboardCoreTest(unittest.TestCase):
    def make_helper(self, backwards_compatible: bool):
        packets = []
        old_backwards_compatible = core.BACKWARDS_COMPATIBLE
        core.BACKWARDS_COMPATIBLE = backwards_compatible
        self.addCleanup(setattr, core, "BACKWARDS_COMPATIBLE", old_backwards_compatible)
        helper = ClipboardHelper.__new__(ClipboardHelper)
        proxy = ClipboardProxy("CLIPBOARD")
        helper.send = lambda *packet: packets.append(packet)
        helper._local_to_remote = {}
        helper._remote_to_local = {}
        helper._greedy = ()
        helper._clipboard_proxies = {"CLIPBOARD": proxy}
        helper.local_selections = ("CLIPBOARD",)
        helper.local_greedy = ()
        helper.filter_res = ()
        helper.max_clipboard_packet_size = core.MAX_CLIPBOARD_PACKET_SIZE
        helper.max_clipboard_receive_size = -1
        helper.max_clipboard_send_size = -1
        helper.init_packet_handlers()
        return helper, proxy, packets

    def test_legacy_clipboard_token_packet(self):
        helper, proxy, packets = self.make_helper(True)
        helper.local_greedy = ("CLIPBOARD",)
        helper._send_clipboard_token_handler(
            proxy,
            {
                "targets": ("UTF8_STRING",),
                "data": {"UTF8_STRING": ("STRING", 8, b"hello")},
            },
        )
        self.assertEqual(
            packets,
            [("clipboard-token", "CLIPBOARD", ("UTF8_STRING",),
              "UTF8_STRING", "STRING", 8, "bytes", b"hello", True, True)],
        )
        self.assertIn("clipboard-token", helper._packet_handlers)

    def test_legacy_packet_uses_first_data_item(self):
        helper, proxy, packets = self.make_helper(True)
        helper._send_clipboard_token_handler(proxy, {
            "targets": ("UTF8_STRING", "image/png"),
            "data": {
                "UTF8_STRING": ("STRING", 8, b"hello"),
                "image/png": ("image/png", 8, b"PNG"),
            },
        })
        self.assertEqual(packets, [(
            "clipboard-token", "CLIPBOARD", ("UTF8_STRING", "image/png"),
            "UTF8_STRING", "STRING", 8, "bytes", b"hello", True, False,
        )])

    def test_modern_clipboard_data_packet(self):
        helper, proxy, packets = self.make_helper(False)
        helper.local_greedy = ("CLIPBOARD",)
        payload = b"hello" * 200
        helper._send_clipboard_token_handler(
            proxy,
            {
                "targets": ("UTF8_STRING",),
                "data": {"UTF8_STRING": ("STRING", 8, payload)},
            },
        )
        self.assertEqual(len(packets), 1)
        packet_type, selection, options = packets[0]
        self.assertEqual(packet_type, "clipboard-data")
        self.assertEqual(selection, "CLIPBOARD")
        self.assertEqual(options["targets"], ("UTF8_STRING",))
        self.assertEqual(options["data"], {
            "UTF8_STRING": ("STRING", 8, "bytes", payload),
        })
        self.assertEqual(options["claim"], True)
        self.assertEqual(options["greedy"], True)
        self.assertNotIn("token", options)
        self.assertNotIn("clipboard-token", helper._packet_handlers)

    def test_modern_packet_defaults(self):
        helper, proxy, _packets = self.make_helper(False)
        helper.process_clipboard_packet(Packet("clipboard-data", "CLIPBOARD", {}))
        self.assertEqual(proxy.tokens, [(None, None, True, False)])

    def test_modern_packet_omits_empty_targets(self):
        helper, proxy, packets = self.make_helper(False)
        helper._send_clipboard_token_handler(proxy, {"targets": (), "data": {}})
        self.assertEqual(packets, [(
            "clipboard-data",
            "CLIPBOARD",
            {"claim": True, "greedy": False},
        )])

    def test_modern_packet_sends_multiple_data_items(self):
        helper, proxy, packets = self.make_helper(False)
        helper._send_clipboard_token_handler(proxy, {
            "targets": ("UTF8_STRING", "image/png"),
            "data": {
                "UTF8_STRING": ("STRING", 8, b"hello", "future-field"),
                "image/png": ("image/png", 8, b"PNG"),
            },
        })
        options = packets[0][2]
        self.assertEqual(options["data"], {
            "UTF8_STRING": ("STRING", 8, "bytes", b"hello"),
            "image/png": ("image/png", 8, "bytes", b"PNG"),
        })

    def test_modern_packet_multiple_targets(self):
        helper, proxy, _packets = self.make_helper(False)
        helper.process_clipboard_packet(Packet(
            "clipboard-data",
            "CLIPBOARD",
            {
                "targets": ("UTF8_STRING", "text/plain"),
                "data": {
                    "UTF8_STRING": ("STRING", 8, "bytes", b"hello", "future-field"),
                    "text/plain": ("text/plain", 8, "bytes", b"world"),
                },
                "claim": False,
                "greedy": True,
                "synchronous": True,
            },
        ))
        self.assertEqual(proxy.tokens, [(
            ("UTF8_STRING", "text/plain"),
            {
                "UTF8_STRING": ("STRING", 8, b"hello"),
                "text/plain": ("text/plain", 8, b"world"),
            },
            False,
            True,
        )])
        self.assertTrue(proxy._greedy_client)

    def test_greedy_capability_backwards_compatibility(self):
        caps = typedict({"greedy": ("CLIPBOARD",)})
        self.assertTrue(caps.boolget("greedy"))
        self.assertEqual(parse_greedy(caps), ("CLIPBOARD",))
        self.assertEqual(parse_greedy(typedict({"greedy": True})), tuple(ALL_CLIPBOARDS))

        helper, _proxy, _packets = self.make_helper(False)
        helper.local_preferred_targets = ()
        helper.local_want_targets = ()
        helper.local_greedy = ("CLIPBOARD",)
        self.assertEqual(helper.get_caps()["greedy"], ("CLIPBOARD",))

    def test_per_selection_greedy(self):
        helper, clipboard, _packets = self.make_helper(False)
        primary = ClipboardProxy("PRIMARY")
        helper._clipboard_proxies["PRIMARY"] = primary
        helper.set_greedy_client(("PRIMARY",))
        self.assertFalse(clipboard._greedy_client)
        self.assertTrue(primary._greedy_client)

        helper._local_to_remote["CLIPBOARD"] = "PRIMARY"
        helper.set_greedy_client(("PRIMARY",))
        self.assertTrue(clipboard._greedy_client)

    def test_outgoing_greedy_is_per_selection(self):
        helper, clipboard, packets = self.make_helper(False)
        primary = ClipboardProxy("PRIMARY")
        helper._clipboard_proxies["PRIMARY"] = primary
        helper.local_greedy = ("PRIMARY",)
        helper._send_clipboard_token_handler(clipboard, {})
        helper._send_clipboard_token_handler(primary, {})
        self.assertFalse(packets[0][2]["greedy"])
        self.assertTrue(packets[1][2]["greedy"])


def main():
    unittest.main()


if __name__ == "__main__":
    main()
