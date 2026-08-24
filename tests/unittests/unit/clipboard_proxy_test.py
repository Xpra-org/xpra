#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest
from io import BytesIO

from xpra.clipboard.proxy import ClipboardProxyCore, filter_data
from xpra.codecs.image_type import get_image_type


class SynchronousProxy(ClipboardProxyCore):
    def __init__(self, responses):
        super().__init__("CLIPBOARD")
        self.responses = responses
        self.requests = []

    def get_contents(self, target, got_contents) -> None:
        self.requests.append(target)
        got_contents(*self.responses.get(target, ("", 0, b"")))


class AsynchronousProxy(ClipboardProxyCore):
    def __init__(self, responses):
        super().__init__("CLIPBOARD")
        self.responses = responses
        self.requests = []
        self.callback = None

    def get_contents(self, target, got_contents) -> None:
        self.requests.append(target)
        self.callback = lambda: got_contents(*self.responses[target])

    def respond(self) -> None:
        callback, self.callback = self.callback, None
        callback()


class ClipboardProxyTest(unittest.TestCase):
    def test_filter_additional_image_formats(self):
        from PIL import Image
        buf = BytesIO()
        Image.new("RGBA", (2, 2), (1, 2, 3, 255)).save(buf, "PNG")
        png = buf.getvalue()
        for target in ("image/webp", "image/bmp"):
            with self.subTest(target=target):
                converted = filter_data("image/png", 8, png, trusted=True, output_dtype=target)
                self.assertEqual(get_image_type(converted), target.split("/", 1)[1])

    def test_get_eager_targets(self):
        proxy = SynchronousProxy({})
        proxy.set_preferred_targets(("text/html", "UTF8_STRING"))
        self.assertEqual(
            proxy.get_eager_targets(("text/uri-list", "UTF8_STRING", "text/html")),
            ("UTF8_STRING", "text/html"),
        )

    def test_local_owner_change_discards_remote_origin(self):
        proxy = SynchronousProxy({})
        proxy._clipboard_origin = "remote-origin"
        proxy.do_owner_changed()
        self.assertEqual(proxy._clipboard_origin, "")

    def test_collect_contents(self):
        proxy = SynchronousProxy({
            "UTF8_STRING": ("UTF8_STRING", 8, b"hello"),
            "text/html": ("text/html", 8, b"<b>hello</b>"),
        })
        results = []
        proxy.collect_contents(("UTF8_STRING", "text/html", "UTF8_STRING", "missing"), results.append)
        self.assertEqual(proxy.requests, ["UTF8_STRING", "text/html", "missing"])
        self.assertEqual(results, [{
            "UTF8_STRING": ("UTF8_STRING", 8, b"hello"),
            "text/html": ("text/html", 8, b"<b>hello</b>"),
        }])

    def test_collect_contents_size_limit(self):
        proxy = SynchronousProxy({
            "too-large": ("text/plain", 8, b"123456"),
            "small": ("text/uri-list", 8, b"uri"),
            "over-budget": ("text/html", 8, b"html"),
        })
        results = []
        proxy.collect_contents(("too-large", "small", "over-budget"), results.append, max_size=5)
        self.assertEqual(results, [{
            "small": ("text/uri-list", 8, b"uri"),
        }])

    def test_collect_contents_asynchronously(self):
        proxy = AsynchronousProxy({
            "text/plain": ("text/plain", 8, b"text"),
            "text/html": ("text/html", 8, b"<b>text</b>"),
        })
        results = []
        proxy.collect_contents(("text/plain", "text/html"), results.append)
        self.assertEqual(proxy.requests, ["text/plain"])
        self.assertEqual(results, [])
        proxy.respond()
        self.assertEqual(proxy.requests, ["text/plain", "text/html"])
        self.assertEqual(results, [])
        proxy.respond()
        self.assertEqual(results, [{
            "text/plain": ("text/plain", 8, b"text"),
            "text/html": ("text/html", 8, b"<b>text</b>"),
        }])


if __name__ == "__main__":
    unittest.main()
