#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest
from unittest.mock import patch

from xpra.clipboard import timeout
from xpra.clipboard.proxy import ClipboardProxyCore
from xpra.clipboard.timeout import ClipboardTimeoutHelper
from xpra.net.common import Packet


class FakeGLib:
    """ records the timers which are still armed """

    def __init__(self):
        self.timers: dict[int, tuple] = {}
        self.counter = 0

    def idle_add(self, callback, *args) -> int:
        return self.timeout_add(0, callback, *args)

    def timeout_add(self, _delay: int, callback, *args) -> int:
        self.counter += 1
        self.timers[self.counter] = (callback, args)
        return self.counter

    def source_remove(self, timer: int) -> None:
        if timer not in self.timers:
            raise ValueError(f"timer {timer} is not armed")
        del self.timers[timer]


class ClipboardProxy(ClipboardProxyCore):
    def __init__(self, selection: str):
        super().__init__(selection)
        self.contents = []

    def got_contents(self, target: str, dtype: str = "", dformat: int = 0, data=None) -> None:
        self.contents.append((target, dtype, dformat, data))


class ClipboardTimeoutTest(unittest.TestCase):

    def make_helper(self):
        glib = FakeGLib()
        patcher = patch.object(timeout, "GLib", glib)
        patcher.start()
        self.addCleanup(patcher.stop)
        helper = ClipboardTimeoutHelper.__new__(ClipboardTimeoutHelper)
        proxy = ClipboardProxy("CLIPBOARD")
        helper.send = lambda *packet: None
        helper.progress_cb = lambda *args: None
        helper._local_to_remote = {}
        helper._clipboard_proxies = {"CLIPBOARD": proxy}
        helper._clipboard_origins = {}
        helper._peer_requests = {}
        helper.max_clipboard_packet_size = 1024
        helper.max_clipboard_receive_size = -1
        helper._clipboard_request_counter = 0
        helper._clipboard_outstanding_requests = {}
        return helper, proxy, glib

    def request(self, helper, proxy, target="UTF8_STRING") -> None:
        helper._send_clipboard_request_handler(proxy, "CLIPBOARD", target)

    def assert_cancelled(self, helper, proxy, glib) -> None:
        # every request must have been answered exactly once, with no data:
        self.assertEqual(proxy.contents, [("UTF8_STRING", "", 0, None), ("TARGETS", "", 0, None)])
        # and no timer must be left armed:
        self.assertEqual(glib.timers, {})
        self.assertEqual(helper._clipboard_outstanding_requests, {})

    def test_client_reset_answers_outstanding_requests(self):
        helper, proxy, glib = self.make_helper()
        self.request(helper, proxy)
        self.request(helper, proxy, "TARGETS")
        self.assertEqual(len(helper._clipboard_outstanding_requests), 2)
        self.assertEqual(len(glib.timers), 2)
        helper.client_reset()
        self.assert_cancelled(helper, proxy, glib)

    def test_cleanup_answers_outstanding_requests(self):
        helper, proxy, glib = self.make_helper()
        self.request(helper, proxy)
        self.request(helper, proxy, "TARGETS")
        helper.cleanup()
        self.assert_cancelled(helper, proxy, glib)

    def test_reply_cancels_the_timer(self):
        helper, proxy, glib = self.make_helper()
        self.request(helper, proxy)
        helper._clipboard_got_contents(0, "STRING", 8, b"hello")
        self.assertEqual(proxy.contents, [("UTF8_STRING", "STRING", 8, b"hello")])
        self.assertEqual(glib.timers, {})
        self.assertEqual(helper._clipboard_outstanding_requests, {})

    def test_no_contents_reply_matches_timeout(self):
        helper, proxy, glib = self.make_helper()
        self.request(helper, proxy)
        helper._process_contents_none(Packet("clipboard-contents-none", 0, "CLIPBOARD"))
        self.assertEqual(proxy.contents, [("UTF8_STRING", "", 0, None)])
        self.assertEqual(glib.timers, {})
        self.assertEqual(helper._clipboard_outstanding_requests, {})

    def test_timeout_answers_the_request(self):
        helper, proxy, glib = self.make_helper()
        self.request(helper, proxy)
        callback, args = glib.timers[1]
        callback(*args)
        self.assertEqual(proxy.contents, [("UTF8_STRING", "", 0, None)])
        self.assertEqual(helper._clipboard_outstanding_requests, {})

    def test_reply_for_another_selection_is_ignored(self):
        helper, proxy, glib = self.make_helper()
        self.request(helper, proxy)
        helper._process_contents(Packet("clipboard-contents", 0, "PRIMARY", "STRING", 8, "bytes", b"hello", 0))
        helper._process_contents_none(Packet("clipboard-contents-none", 0, "PRIMARY"))
        self.assertEqual(proxy.contents, [])
        # the request is still pending, and its timer answers it:
        callback, args = glib.timers[1]
        callback(*args)
        self.assertEqual(proxy.contents, [("UTF8_STRING", "", 0, None)])

    def test_html5_reply(self):
        # without the `truncated` field:
        helper, proxy, glib = self.make_helper()
        self.request(helper, proxy)
        helper._process_contents(Packet("clipboard-contents", 0, "CLIPBOARD", "UTF8_STRING", 8, "bytes", "hello"))
        self.assertEqual(proxy.contents, [("UTF8_STRING", "UTF8_STRING", 8, b"hello")])
        self.assertEqual(glib.timers, {})

    def test_targets_reply_must_be_atoms(self):
        helper, proxy, glib = self.make_helper()
        self.request(helper, proxy, "TARGETS")
        # ie: the html5 client answers every request with text:
        helper._process_contents(Packet("clipboard-contents", 0, "CLIPBOARD", "UTF8_STRING", 8, "bytes", b"hello", 0))
        self.assertEqual(proxy.contents, [("TARGETS", "", 0, None)])
        self.assertEqual(glib.timers, {})

    def test_outstanding_requests_limit(self):
        helper, proxy, glib = self.make_helper()
        for _ in range(timeout.MAX_CLIPBOARD_OUTSTANDING_REQUESTS):
            self.request(helper, proxy)
        self.assertEqual(len(helper._clipboard_outstanding_requests), timeout.MAX_CLIPBOARD_OUTSTANDING_REQUESTS)
        sent = []
        helper.send = lambda *packet: sent.append(packet)
        self.request(helper, proxy, "TARGETS")
        self.assertEqual(sent, [])
        self.assertEqual(len(helper._clipboard_outstanding_requests), timeout.MAX_CLIPBOARD_OUTSTANDING_REQUESTS)
        # answered from the main loop, not from the signal handler:
        self.assertEqual(proxy.contents, [])
        callback, args = glib.timers[glib.counter]
        callback(*args)
        self.assertEqual(proxy.contents, [("TARGETS", "", 0, None)])
        helper.cleanup()


def main():
    unittest.main()


if __name__ == "__main__":
    main()
