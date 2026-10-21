#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import unittest
from time import monotonic, sleep

from xpra.os_util import gi_import

GLib = gi_import("GLib")

SELECTIONS = ("CLIPBOARD", "PRIMARY")
ORIGIN = "application/x-xpra-clipboard-origin"


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

    def __init__(self):
        self.connections: list[tuple[str, object]] = []

    def connect(self, signal, callback):
        self.connections.append((signal, callback))
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
        self.origin = False
        self.reads: list[tuple[int, str, int]] = []

    def source_targets(self, source_ptr: int) -> tuple[str, ...]:
        targets = (f"application/x-test-{source_ptr}", )
        return (ORIGIN, ) + targets if self.origin else targets

    def send_source(self, source_ptr: int, target: str, fd: int) -> None:
        # the proxy closes its own end as soon as this returns,
        # so hold a copy to answer whenever the test wants to:
        self.reads.append((source_ptr, target, os.dup(fd)))

    def complete(self, index: int, data: bytes) -> None:
        _, _, fd = self.reads[index]
        os.write(fd, data)
        os.close(fd)

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

    def test_isolated_owner_change_is_not_delayed(self):
        helper, tokens = self.make_helper()
        for selection, proxy in helper._clipboard_proxies.items():
            proxy.selection_changed(1)
            self.assertEqual(len(tokens[selection]), 1)
            self.assertEqual(tokens[selection][0]["targets"], ("application/x-test-1", ))
            self.assertEqual(proxy._emit_token_timer, 0)
            self.assertEqual(proxy._sent_token_events, 1)

    def test_burst_is_coalesced_into_the_latest_owner(self):
        helper, tokens = self.make_helper()
        for selection, proxy in helper._clipboard_proxies.items():
            for source_ptr in range(1, 101):
                proxy.selection_changed(source_ptr)
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
            proxy.selection_changed(1)
            proxy.selection_changed(2)
            self.assertNotEqual(proxy._emit_token_timer, 0)
            proxy.got_token(("text/plain", ), {"text/plain": ("text/plain", 8, b"remote")})
            self.assertEqual(proxy._emit_token_timer, 0)
            self.assertFalse(spin_until(lambda: len(tokens[selection]) > 1, timeout=0.5))

    def test_stale_origin_read_is_dropped_when_the_pointer_is_reused(self):
        helper, tokens = self.make_helper()
        for selection, proxy in helper._clipboard_proxies.items():
            api = proxy.selection_api
            api.origin = True
            proxy.selection_changed(0x100)
            # the owner goes away, and the next source lands at the same address:
            proxy.selection_changed(0)
            proxy.selection_changed(0x100)
            self.assertEqual([(ptr, target) for ptr, target, _ in api.reads], [(0x100, ORIGIN)] * 2)
            api.complete(0, b"stale-origin")
            self.assertFalse(spin_until(lambda: proxy._clipboard_origin, timeout=0.5))
            self.assertEqual(tokens[selection], [])
            api.complete(1, b"current-origin")
            self.assertTrue(spin_until(lambda: len(tokens[selection]) == 1))
            self.assertEqual(proxy._clipboard_origin, "current-origin")
            self.assertEqual(tokens[selection][0]["targets"], ("application/x-test-256", ))

    def test_each_selection_is_built_from_its_own_native_types(self):
        helper, _ = self.make_helper()
        proxies = helper._clipboard_proxies
        self.assertEqual(helper.compositor.connections, [
            (proxies[selection].SELECTION_SIGNAL, proxies[selection].selection_changed) for selection in SELECTIONS
        ])
        for attribute in ("SELECTION_SIGNAL", "SELECTION_API", "SOURCE_CLASS"):
            values = [getattr(proxies[selection], attribute) for selection in SELECTIONS]
            self.assertNotEqual(values[0], values[1], f"both selections share {attribute}")

    def test_no_token_when_we_cannot_send(self):
        helper, tokens = self.make_helper(can_send=False)
        for selection, proxy in helper._clipboard_proxies.items():
            proxy.selection_changed(1)
            self.assertEqual(tokens[selection], [])
            self.assertEqual(proxy._emit_token_timer, 0)


if __name__ == "__main__":
    unittest.main()
