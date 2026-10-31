#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

"""
Screenshots of monitors that are not at the origin of the virtual desktop.
These tests are skipped on non-Windows platforms.
"""

import sys
import unittest
from unittest.mock import patch

from xpra.codecs.image import ImageWrapper

WIN32 = sys.platform == "win32"


def make_image(w: int, h: int) -> ImageWrapper:
    return ImageWrapper(0, 0, w, h, b"\0" * w * h * 4, "BGRX", 24, w * 4, 4, ImageWrapper.PACKED, True)


class FakeCapture:
    """ a per-monitor capture: it works in coordinates relative to its monitor """

    def __init__(self):
        self.requests = []

    def get_image(self, x: int, y: int, w: int, h: int):
        self.requests.append((x, y, w, h))
        return make_image(w, h)

    def take_screenshot(self):
        raise RuntimeError("this would be the whole desktop")


@unittest.skipUnless(WIN32, "the win32 platform code is only available on MS Windows")
class Win32ShadowScreenshotTest(unittest.TestCase):

    def test_monitor_screenshot(self):
        from xpra.platform.win32.shadow.model import PerMonitorCaptureWindowModel
        capture = FakeCapture()
        rwm = PerMonitorCaptureWindowModel(capture, "monitor 1", (1920, 0, 64, 32))
        w, h, encoding, _rowstride, _data = rwm.take_screenshot()
        self.assertEqual((w, h, encoding), (64, 32, "png"))
        self.assertEqual(capture.requests, [(0, 0, 64, 32)])

    def test_gdi_screenshot_ignores_the_offset(self):
        from xpra.platform.win32 import gdi_screen_capture
        for metrics, offset, request in (
            # a monitor on the right of the primary one:
            ((0, 0, 80, 20), (40, 0), (-40, 0, 80, 20)),
            # a monitor on the left of the primary one:
            ((-40, 0, 80, 20), (-40, 0), (0, 0, 80, 20)),
        ):
            with self.subTest(offset=offset):
                capture = gdi_screen_capture.GDICapture(*offset)
                requests = []

                def get_image(*args):
                    requests.append(args)
                    return make_image(*metrics[2:])

                capture.get_image = get_image
                with patch.object(gdi_screen_capture, "get_virtualscreenmetrics", return_value=metrics):
                    w, h, encoding, _rowstride, _data = capture.take_screenshot()
                self.assertEqual((w, h, encoding), (80, 20, "png"))
                # `get_image()` adds the offset back, which gives us the virtual screen:
                self.assertEqual(requests, [request])


def main():
    unittest.main()


if __name__ == "__main__":
    main()
