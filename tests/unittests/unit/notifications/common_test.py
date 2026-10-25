#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2020-2022 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import tempfile
import unittest
from io import BytesIO

from xpra.notifications import common
from unit.test_util import silence_error


class TestCommon(unittest.TestCase):

    def test_strip_unsafe_markup(self):
        strip = common.strip_unsafe_markup
        self.assertEqual(strip("plain text, 1 < 2"), "plain text, 1 < 2")
        self.assertEqual(strip("<b>bold</b> <i>it</i> <u>u</u>"), "<b>bold</b> <i>it</i> <u>u</u>")
        self.assertEqual(strip('see <a href="https://example.com">this</a>'), "see this")
        self.assertEqual(strip("<A HREF='file:///etc'>x</A >"), "x")
        self.assertEqual(strip('<img src="/etc/passwd" alt="x"/>after'), "after")
        self.assertEqual(strip("< img\nsrc=x>"), "")
        self.assertEqual(strip("<im<img>g src=x>"), "")
        self.assertEqual(strip("<<a>a href=x>y"), "y")
        self.assertEqual(strip("<abbr>x</abbr> <image>"), "<abbr>x</abbr> <image>")

    def test_parse_image_data(self):
        p = common.parse_image_data
        with silence_error(common):
            assert p(None) is None
            assert p((1, 2, 3)) is None
            assert p((1, 2, 3, 4, 5, 6, 7)) is None
        assert p((10, 10, 40, True, 32, 4, b"0"*40*10)) is not None
        assert p((10, 10, 40, False, 24, 4, b"0"*40*10)) is not None
        assert p((10, 10, 30, False, 24, 3, b"0"*30*10)) is not None

    def test_parse_image_data_colours(self):
        Image = common.PIL_Image()
        for mode, pixels in (
            ("RGB", bytes((255, 0, 0, 0, 0, 255, 12, 34, 56, 78, 90, 123))),
            ("RGBA", bytes((255, 0, 0, 255, 0, 0, 255, 128, 12, 34, 56, 0, 78, 90, 123, 64))),
        ):
            channels = len(mode)
            row_bytes = 2 * channels
            for padding in (0, 3):
                padded = pixels[:row_bytes] + b"\x99" * padding + pixels[row_bytes:]
                for container in (bytes, list, tuple):
                    with self.subTest(mode=mode, padding=padding, container=container.__name__):
                        icon = common.parse_image_data(
                            (2, 2, row_bytes + padding, mode == "RGBA", 8, channels, container(padded)))
                        self.assertIsNotNone(icon)
                        self.assertEqual(icon[:3], ("png", 2, 2))
                        with Image.open(BytesIO(icon[3])) as image:
                            self.assertEqual(image.mode, mode)
                            self.assertEqual(image.tobytes(), pixels)

    def test_parse_image_path(self):
        iconname = "xpra"
        from xpra.platform.paths import get_icon_filename, get_icon_dir
        filename = get_icon_filename(iconname)
        if not filename:
            raise RuntimeError(f"no icon filename found for icon directory {get_icon_dir()} and icon name {iconname!r}")
        if not common.parse_image_path(filename):
            raise RuntimeError(f"failed to parse image path for filename {filename!r}, icon {iconname!r} and icon_dir={get_icon_dir()!r}")
        f = tempfile.NamedTemporaryFile(prefix="test-invalid-file", delete=False)
        try:
            f.file.write(b"0000000000000001111111111111111111111")
            f.file.flush()
            f.close()
            for x in ("", None, "/invalid-path", f.name):
                with silence_error(common):
                    assert common.parse_image_path(x) is None
        finally:
            os.unlink(f.name)


def main():
    unittest.main()

if __name__ == '__main__':
    main()
