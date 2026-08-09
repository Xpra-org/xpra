#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest

from xpra.clipboard.primary import PrimaryProxyMixin
from xpra.clipboard.proxy import ClipboardProxyCore


class StubProxy(ClipboardProxyCore):
    """stands in for a platform specific clipboard proxy"""

    def __init__(self, selection: str):
        super().__init__(selection)
        self.requests = []
        self.tokens = []

    def send_clipboard_request_handler(self, proxy, selection: str, target: str) -> None:
        self.requests.append((selection, target))

    def do_emit_token(self) -> None:
        self.tokens.append(self._selection)


class StubPrimaryProxy(PrimaryProxyMixin, StubProxy):

    def __init__(self, set_clipboard_text):
        self.init_primary(set_clipboard_text)
        super().__init__("PRIMARY")


class PrimaryProxyTest(unittest.TestCase):

    def make_proxy(self):
        texts = []
        proxy = StubPrimaryProxy(texts.append)
        self.addCleanup(proxy.cleanup)
        proxy.set_enabled(True)
        proxy.set_direction(True, True)
        return proxy, texts

    def test_receive_only(self):
        proxy, _ = self.make_proxy()
        # we can never claim a selection that does not exist locally:
        self.assertFalse(proxy._can_send)
        self.assertTrue(proxy._can_receive)
        proxy.emit_token()
        self.assertEqual(proxy.tokens, [])

    def test_token_schedules_request(self):
        proxy, _ = self.make_proxy()
        proxy.got_token(())
        # the request must be delayed:
        self.assertTrue(proxy.request_timer)
        self.assertEqual(proxy.requests, [])
        self.assertTrue(proxy.get_info()["request-scheduled"])
        # a second token does not schedule a second request:
        timer = proxy.request_timer
        proxy.got_token(())
        self.assertEqual(proxy.request_timer, timer)
        # fire the timer:
        proxy.request_contents()
        self.assertEqual(proxy.requests, [("PRIMARY", "UTF8_STRING")])
        self.assertFalse(proxy.request_timer)

    def test_no_request_when_disabled(self):
        proxy, _ = self.make_proxy()
        proxy.set_enabled(False)
        proxy.got_token(())
        self.assertFalse(proxy.request_timer)
        proxy.set_enabled(True)
        proxy.set_direction(True, False)
        proxy.got_token(())
        self.assertFalse(proxy.request_timer)

    def test_cancel_request(self):
        proxy, _ = self.make_proxy()
        proxy.schedule_request()
        self.assertTrue(proxy.request_timer)
        proxy.cancel_request()
        self.assertFalse(proxy.request_timer)
        # cancelling again is a no-op:
        proxy.cancel_request()
        self.assertFalse(proxy.request_timer)

    def test_cancel_discards_the_reply(self):
        proxy, texts = self.make_proxy()
        proxy.schedule_request()
        proxy.request_contents()
        # too late to cancel the request itself, but the reply must be discarded:
        proxy.cancel_request()
        self.assertEqual(proxy.get_info()["requests-stale"], 1)
        proxy.got_contents("UTF8_STRING", "UTF8_STRING", 8, b"stale")
        self.assertEqual(texts, [])
        self.assertEqual(proxy.get_info()["requests-stale"], 0)
        # but the reply to the next request is used:
        proxy.request_contents()
        proxy.got_contents("UTF8_STRING", "UTF8_STRING", 8, b"fresh")
        self.assertEqual(texts, ["fresh"])

    def test_cancel_discards_every_request_sent(self):
        proxy, texts = self.make_proxy()
        proxy.request_contents()
        proxy.request_contents()
        proxy.cancel_request()
        self.assertEqual(proxy.get_info()["requests-stale"], 2)
        for _ in range(2):
            proxy.got_contents("UTF8_STRING", "UTF8_STRING", 8, b"stale")
        self.assertEqual(texts, [])
        self.assertEqual(proxy.get_info()["requests-pending"], 0)

    def test_token_data_is_not_discarded(self):
        proxy, texts = self.make_proxy()
        # a request is in flight when the token arrives with the data:
        proxy.request_contents()
        proxy.got_token(("UTF8_STRING",), {"UTF8_STRING": ("UTF8_STRING", 8, b"hello")})
        self.assertEqual(texts, ["hello"])
        # and the reply to the superseded request is still discarded:
        proxy.got_contents("UTF8_STRING", "UTF8_STRING", 8, b"stale")
        self.assertEqual(texts, ["hello"])

    def test_cleanup_cancels_request(self):
        proxy, _ = self.make_proxy()
        proxy.schedule_request()
        proxy.cleanup()
        self.assertFalse(proxy.request_timer)

    def test_token_with_data(self):
        proxy, texts = self.make_proxy()
        proxy.schedule_request()
        proxy.got_token(("UTF8_STRING",), {"UTF8_STRING": ("UTF8_STRING", 8, b"hello")})
        # no need to request anything, we already have the data:
        self.assertFalse(proxy.request_timer)
        self.assertEqual(texts, ["hello"])

    def test_token_data_prefers_plain_text(self):
        proxy, texts = self.make_proxy()
        proxy.got_token(("text/html", "UTF8_STRING"), {
            "text/html": ("text/html", 8, b"<b>hello</b>"),
            "UTF8_STRING": ("UTF8_STRING", 8, b"hello"),
        })
        self.assertEqual(texts, ["hello"])

    def test_token_data_without_plain_text(self):
        proxy, texts = self.make_proxy()
        proxy.got_token(("text/html",), {"text/html": ("text/html", 8, b"<b>hello</b>")})
        self.assertEqual(texts, [])

    def test_got_contents(self):
        proxy, texts = self.make_proxy()
        proxy.got_contents("STRING", "STRING", 8, b"hello")
        self.assertEqual(texts, ["hello"])
        # empty, unknown or non-text replies are ignored:
        proxy.got_contents("UTF8_STRING")
        proxy.got_contents("UTF8_STRING", "UTF8_STRING", 8, b"")
        proxy.got_contents("image/png", "image/png", 8, b"not text")
        proxy.got_contents("TARGETS", "ATOM", 32, ("UTF8_STRING",))
        self.assertEqual(texts, ["hello"])

    def test_utf8_contents(self):
        proxy, texts = self.make_proxy()
        proxy.got_contents("UTF8_STRING", "UTF8_STRING", 8, "été".encode("utf8"))
        self.assertEqual(texts, ["été"])

    def test_utf8_fallback_contents(self):
        proxy, texts = self.make_proxy()
        for target in ("text/csv", "text/tab-separated-values", "text/markdown"):
            with self.subTest(target=target):
                proxy.got_contents(target, target, 8, "été".encode("utf8"))
        self.assertEqual(texts, ["été", "été", "été"])


def main():
    unittest.main()


if __name__ == "__main__":
    main()
