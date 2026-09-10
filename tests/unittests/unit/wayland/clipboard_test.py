#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest
from time import monotonic, sleep

from xpra.os_util import gi_import

GLib = gi_import("GLib")

SELECTIONS = ("CLIPBOARD", "PRIMARY")


def spin_until(predicate, timeout=2) -> bool:
    context = GLib.MainContext.default()
    deadline = monotonic() + timeout
    while monotonic() < deadline and not predicate():
        while context.pending():
            context.iteration(False)
        sleep(0.005)
    return predicate()


class FakeCompositor:
    """The proxies only use the compositor to subscribe to selection changes"""

    def connect(self, _signal, callback):
        return callback

    def disconnect(self, _signal, _callback) -> None:
        pass

    def get_display_ptr(self) -> int:
        return 0

    def get_seat_ptr(self) -> int:
        return 0


class FakeSelectionAPI:
    """Stand in for the native selection, keyed by a fake source pointer"""

    def __init__(self):
        self.source = None

    def source_targets(self, source_ptr: int) -> tuple[str, ...]:
        return (f"application/x-test-{source_ptr}", )

    def send_source(self, source_ptr: int, _target: str, fd: int) -> None:
        pass

    def set_source(self, source) -> None:
        self.source = source

    def clear(self) -> None:
        self.source = None


class WaylandClipboardTokenTest(unittest.TestCase):

    def make_helper(self, can_send=True):
        # a missing native extension is a failure, not a reason to skip:
        from xpra.wayland.server.clipboard import WaylandClipboard
        kwargs = {"can-send": can_send, "can-receive": True}
        helper = WaylandClipboard(lambda *_packet: None, compositor=FakeCompositor(), **kwargs)
        self.addCleanup(helper.cleanup)
        helper.enable_selections(SELECTIONS)
        tokens: dict[str, list] = {selection: [] for selection in SELECTIONS}
        for selection, proxy in helper._clipboard_proxies.items():
            proxy.selection_api = FakeSelectionAPI()
            proxy.set_want_targets(True)
            proxy.connect("send-clipboard-token", lambda _proxy, token, l=tokens[selection]: l.append(token))
        return helper, tokens

    @staticmethod
    def owner_changed(proxy, source_ptr: int) -> None:
        if proxy._selection == "CLIPBOARD":
            proxy.selection_changed(source_ptr)
        else:
            proxy.primary_selection_changed(source_ptr)

    def test_isolated_owner_change_is_not_delayed(self):
        helper, tokens = self.make_helper()
        for selection, proxy in helper._clipboard_proxies.items():
            self.owner_changed(proxy, 1)
            self.assertEqual(len(tokens[selection]), 1)
            self.assertEqual(tokens[selection][0]["targets"], ("application/x-test-1", ))
            self.assertEqual(proxy._emit_token_timer, 0)
            self.assertEqual(proxy._sent_token_events, 1)

    def test_burst_is_coalesced_into_the_latest_owner(self):
        helper, tokens = self.make_helper()
        for selection, proxy in helper._clipboard_proxies.items():
            for source_ptr in range(1, 101):
                self.owner_changed(proxy, source_ptr)
            # an owner burst must not become one wire packet per change:
            self.assertEqual(len(tokens[selection]), 1)
            self.assertNotEqual(proxy._emit_token_timer, 0)
        for selection, proxy in helper._clipboard_proxies.items():
            self.assertTrue(spin_until(lambda: len(tokens[selection]) == 2))
            self.assertEqual(tokens[selection][-1]["targets"], ("application/x-test-100", ))
            self.assertEqual(proxy._emit_token_timer, 0)
            self.assertEqual(proxy._sent_token_events, 2)

    def test_remote_token_cancels_the_one_we_had_scheduled(self):
        helper, tokens = self.make_helper()
        for selection, proxy in helper._clipboard_proxies.items():
            self.owner_changed(proxy, 1)
            self.owner_changed(proxy, 2)
            self.assertNotEqual(proxy._emit_token_timer, 0)
            proxy.got_token(("text/plain", ), {"text/plain": ("text/plain", 8, b"remote")})
            self.assertEqual(proxy._emit_token_timer, 0)
            self.assertFalse(spin_until(lambda: len(tokens[selection]) > 1, timeout=0.5))

    def test_no_token_when_we_cannot_send(self):
        helper, tokens = self.make_helper(can_send=False)
        for selection, proxy in helper._clipboard_proxies.items():
            self.owner_changed(proxy, 1)
            self.assertEqual(tokens[selection], [])
            self.assertEqual(proxy._emit_token_timer, 0)


if __name__ == "__main__":
    unittest.main()
