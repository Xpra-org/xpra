#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest
from types import SimpleNamespace

from xpra.os_util import OSX


@unittest.skipUnless(OSX, "macOS clipboard test")
class DarwinClipboardTargetsTest(unittest.TestCase):

    def test_image_targets(self) -> None:
        from AppKit import NSPasteboardTypePNG, NSTIFFPboardType
        from xpra.platform.darwin.ctypes_clipboard import OSXClipboardProxy, NSPasteboardTypeJPEG

        def targets(*types):
            pasteboard = SimpleNamespace(types=lambda: types)
            return OSXClipboardProxy.get_targets(SimpleNamespace(pasteboard=pasteboard))

        png = targets(NSPasteboardTypePNG)
        self.assertIn("image/png", png)
        self.assertNotIn("image/jpeg", png)
        self.assertNotIn("image/tiff", png)

        tiff = targets(NSTIFFPboardType)
        self.assertIn("image/png", tiff)
        self.assertIn("image/tiff", tiff)
        self.assertNotIn("image/jpeg", tiff)

        jpeg = targets(NSPasteboardTypePNG, NSPasteboardTypeJPEG)
        self.assertIn("image/jpeg", jpeg)


if __name__ == "__main__":
    unittest.main()
