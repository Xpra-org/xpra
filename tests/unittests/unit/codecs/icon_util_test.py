#!/usr/bin/env python3

import os
import tempfile
import unittest
from unittest.mock import patch


class TestIconUtil(unittest.TestCase):

    def test_load_icon_from_xpm_failure_returns_empty(self):
        with patch("PIL.Image.open", side_effect=ValueError("decode failed")):
            from xpra.codecs.icon_util import load_icon_from_file
            icon = load_icon_from_file("/tmp/test-icon.xpm")

        self.assertEqual(icon, ())

    def test_load_icon_rejects_unsupported_type(self):
        from xpra.codecs.icon_util import load_icon_from_file

        with tempfile.NamedTemporaryFile(suffix=".tiff", delete=False) as f:
            f.write(b"II*\x00" + b"\x00" * 40)
            filename = f.name
        try:
            self.assertEqual(load_icon_from_file(filename), ())
        finally:
            os.unlink(filename)

    def test_load_icon_preserves_jpeg_type(self):
        from xpra.codecs.icon_util import load_icon_from_file

        with tempfile.NamedTemporaryFile(suffix=".jpeg", delete=False) as f:
            f.write(b"\xff\xd8\xff" + b"\x00" * 40)
            filename = f.name
        try:
            icon = load_icon_from_file(filename)
        finally:
            os.unlink(filename)

        self.assertEqual(icon, (b"\xff\xd8\xff" + b"\x00" * 40, "jpeg"))


def main():
    unittest.main()


if __name__ == "__main__":
    main()
