#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest

from xpra.clipboard.core import ClipboardProtocolHelperCore
from xpra.clipboard.proxy import ClipboardProxyCore


class ClipboardHelper(ClipboardProtocolHelperCore):
    def make_proxy(self, selection: str):
        return ClipboardProxyCore(selection)


class ClipboardTranslationTest(unittest.TestCase):

    def test_remote_clipboard_translation(self):
        # The client passes only the selections chosen on the command line.
        helper = ClipboardHelper(lambda *_packet: None, **{
            "clipboard.local": "CLIPBOARD",
            "clipboard.remote": "PRIMARY",
        })
        self.addCleanup(helper.cleanup)
        self.assertEqual(helper.local_to_remote("CLIPBOARD"), "PRIMARY")
        self.assertEqual(helper.remote_to_local("PRIMARY"), "CLIPBOARD")
        self.assertIn("PRIMARY", helper.get_remote_selections())

    def test_invalid_remote_clipboard(self):
        helper = ClipboardHelper(lambda *_packet: None, **{
            "clipboard.local": "CLIPBOARD",
            "clipboard.remote": "INVALID",
        })
        self.addCleanup(helper.cleanup)
        self.assertEqual(helper.local_to_remote("CLIPBOARD"), "CLIPBOARD")

    def test_explicit_selections_limit_translation(self):
        helper = ClipboardHelper(lambda *_packet: None, **{
            "clipboards.local": ("CLIPBOARD",),
            "clipboards.remote": ("SECONDARY",),
            "clipboard.remote": "PRIMARY",
        })
        self.addCleanup(helper.cleanup)
        self.assertEqual(helper.local_to_remote("CLIPBOARD"), "SECONDARY")
        self.assertEqual(helper.get_remote_selections(), ["SECONDARY"])


if __name__ == "__main__":
    unittest.main()
