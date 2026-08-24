#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# This file is released under the GNU GPL v2, or, at your option, any later version.

import unittest
from types import SimpleNamespace

from xpra.client.gui.window_base import ClientWindowBase
from xpra.net.common import BACKWARDS_COMPATIBLE
from xpra.util.objects import typedict


class WindowMetadataTest(unittest.TestCase):

    @staticmethod
    def make_window():
        window = object.__new__(ClientWindowBase)
        window.content_types = ()
        window._backing = SimpleNamespace(content_types=())
        window._metadata = typedict()
        return window

    def test_content_types_update_window_and_backing(self):
        window = self.make_window()
        window.set_metadata(typedict({"content-types": ("browser", "video")}))
        self.assertEqual(window.content_types, ("browser", "video"))
        self.assertEqual(window._backing.content_types, ("browser", "video"))

    def test_content_types_take_precedence_over_legacy_value(self):
        window = self.make_window()
        window.set_metadata(typedict({
            "content-types": ("text",),
            "content-type": "browser+video",
        }))
        self.assertEqual(window.content_types, ("text",))

    def test_legacy_content_type_is_compatibility_only(self):
        window = self.make_window()
        window.set_metadata(typedict({"content-type": "browser+video"}))
        expected = ("browser", "video") if BACKWARDS_COMPATIBLE else ()
        self.assertEqual(window.content_types, expected)
        if BACKWARDS_COMPATIBLE:
            self.assertEqual(window._metadata, {"content-types": expected})

    def test_legacy_metadata_is_normalized_or_ignored(self):
        window = self.make_window()
        window._client = SimpleNamespace(readonly=False)
        window._size = (100, 100)
        window.update_metadata(typedict({"content-type": "text"}))
        expected = {"content-types": ("text",)} if BACKWARDS_COMPATIBLE else {}
        self.assertEqual(window._metadata, expected)


def main():
    unittest.main()


if __name__ == "__main__":
    main()
