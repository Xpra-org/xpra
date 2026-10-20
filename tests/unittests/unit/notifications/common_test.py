#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2020 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import tempfile
import unittest
from unittest.mock import patch

from xpra.notification import common
from unit.test_util import silence_error


class TestCommon(unittest.TestCase):

    def test_validated_hints(self):
        hints = common.validated_hints({
            "urgency": "2", "resident": 1, "category": "email", "unknown": "ignored",
        })
        self.assertEqual(hints, {"urgency": 2, "resident": True, "category": "email"})
        self.assertEqual(common.validated_hints({"x": object()}), {})
        self.assertEqual(common.validated_hints({"urgency": 7}), {"urgency": 2})
        self.assertEqual(common.validated_hints({"urgency": -1}), {"urgency": 0})
        self.assertEqual(common.validated_hints({"category": "im\x00.received\ud800"}), {"category": "im.received?"})
        # a remote application must not be able to claim to be a local one:
        self.assertEqual(common.validated_hints({"desktop-entry": "org.gnome.Settings"}), {})

    def test_strip_unsafe_markup(self):
        strip = common.strip_unsafe_markup
        self.assertEqual(strip("plain text, 1 < 2"), "plain text, 1 < 2")
        self.assertEqual(strip("<b>bold</b> <i>it</i> <u>u</u>"), "<b>bold</b> <i>it</i> <u>u</u>")
        self.assertEqual(strip('see <a href="https://example.com">this</a>'), "see this")
        self.assertEqual(strip("<A HREF='file:///etc'>x</A >"), "x")
        self.assertEqual(strip('<img src="/etc/passwd" alt="x"/>after'), "after")
        self.assertEqual(strip("< img\nsrc=x>"), "")
        # removing a tag must not reveal another one:
        self.assertEqual(strip("<im<img>g src=x>"), "")
        self.assertEqual(strip("<<a>a href=x>y"), "y")
        # not the tags we're looking for:
        self.assertEqual(strip("<abbr>x</abbr> <image>"), "<abbr>x</abbr> <image>")

    def test_single_line(self):
        self.assertEqual(common.single_line("Mail\u202e\n(local)"), "Mail (local)")
        self.assertEqual(common.single_line("a\tb\r\nc\u2028d\x00\x1b[31m\u2066"), "a b  c d[31m")
        self.assertEqual(common.single_line("caf\u00e9 \U0001f468\u200d\U0001f469"), "caf\u00e9 \U0001f468\u200d\U0001f469")

    def test_image_data_hint_precedence(self):
        hints = {"image-path": "/first", "image_data": (1, 2, 3)}
        with patch.object(common, "parse_image_data", return_value=None) as parse_data, \
                patch.object(common, "parse_image_path", return_value=("png", 1, 1, b"data")) as parse_path:
            self.assertEqual(common.image_data_hint(hints), ("png", 1, 1, b"data"))
            parse_data.assert_called_once_with((1, 2, 3))
            parse_path.assert_called_once_with("/first")
        self.assertNotIn("image_data", hints)
        self.assertNotIn("image-path", hints)

    def test_decompress_image_data(self):
        icon = common.image_data(common.PIL_Image().new("RGBA", (2, 3), (1, 2, 3, 4)))
        result = common.decompress_image_data(icon)
        self.assertEqual(result[:6], (2, 3, 8, True, 8, 4))
        self.assertEqual(len(result[6]), 24)
        with silence_error(common):
            self.assertEqual(common.decompress_image_data(("png", 1, 1, b"invalid")),
                             (0, 0, 0, False, 0, 0, bytearray()))

    def test_parse_image_data(self):
        p = common.parse_image_data
        with silence_error(common):
            assert p(None) is None
            assert p((1, 2, 3)) is None
            assert p((1, 2, 3, 4, 5, 6, 7)) is None
        assert p((10, 10, 40, True, 32, 4, b"0"*40*10)) is not None
        assert p((10, 10, 40, False, 24, 4, b"0"*40*10)) is not None
        assert p((10, 10, 30, False, 24, 3, b"0"*30*10)) is not None

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
            for x in ("", "/invalid-path", f.name):
                with silence_error(common):
                    try:
                        assert common.parse_image_path(x) is None
                    except TypeError:
                        pass
        finally:
            os.unlink(f.name)

    def test_get_notification_icon(self):
        image = common.PIL_Image().new("RGB", (300, 100), (1, 2, 3))
        with patch.object(common, "get_gtk_theme_icon", return_value=image):
            icon = common.get_notification_icon("test-icon")
        self.assertEqual(icon[:3], ("png", 256, 256))
        self.assertTrue(icon[3].startswith(b"\x89PNG"))
        self.assertIsNone(common.get_notification_icon(""))


def main():
    unittest.main()


if __name__ == '__main__':
    main()
