#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest
from io import BytesIO
from unittest.mock import MagicMock, patch


def png_data(width: int, height: int) -> bytes:
    from PIL import Image
    buf = BytesIO()
    Image.new("RGB", (width, height)).save(buf, "PNG")
    return buf.getvalue()


class WebcamWindowTest(unittest.TestCase):

    def test_dimensions_are_checked_before_native_decode(self):
        from xpra.client.gtk3 import webcam_window
        with patch.object(webcam_window, "load_pixbuf") as load_pixbuf, \
             patch.object(webcam_window, "get_pillow_pixbuf") as get_pillow_pixbuf:
            self.assertIsNone(webcam_window.get_pixbuf("png", png_data(8, 8), 4, 4))
        load_pixbuf.assert_not_called()
        get_pillow_pixbuf.assert_not_called()

    def test_matching_dimensions_reach_native_decoder(self):
        from xpra.client.gtk3 import webcam_window
        pixbuf = MagicMock()
        pixbuf.get_width.return_value = 4
        pixbuf.get_height.return_value = 4
        with patch.object(webcam_window, "load_pixbuf", return_value=pixbuf) as load_pixbuf:
            self.assertIs(webcam_window.get_pixbuf("png", png_data(4, 4), 4, 4), pixbuf)
        load_pixbuf.assert_called_once()


if __name__ == "__main__":
    unittest.main()
