#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Netflix, Inc.
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.
# ABOUTME: Tests for xpra.codecs.constants — frozen sets/tuples that other
# ABOUTME: codec code relies on for "which formats carry meaningful alpha."

import unittest

from xpra.codecs.constants import ALPHA_FORMATS


class TestAlphaFormats(unittest.TestCase):

    def test_contains_real_alpha_rgb_formats(self):
        for fmt in ("BGRA", "RGBA", "ABGR", "ARGB"):
            self.assertIn(fmt, ALPHA_FORMATS, f"{fmt} should be in ALPHA_FORMATS")

    def test_excludes_yuv_formats_with_padding_a(self):
        # AYUV / Y410 carry "A" in the name but the byte is padding from the
        # producer (Intel oneVPL HEVC RExt fills 0xFF). The strip-by-name
        # heuristic that ALPHA_FORMATS replaces would have caught these.
        for fmt in ("AYUV", "Y410"):
            self.assertNotIn(fmt, ALPHA_FORMATS, f"{fmt} should not be in ALPHA_FORMATS")

    def test_excludes_padded_rgb_formats(self):
        for fmt in ("BGRX", "RGBX", "XBGR", "XRGB"):
            self.assertNotIn(fmt, ALPHA_FORMATS)

    def test_excludes_planar_rgb(self):
        self.assertNotIn("GBRP", ALPHA_FORMATS)
        self.assertNotIn("GBRP10", ALPHA_FORMATS)

    def test_is_frozen(self):
        # The set must be a frozenset so callers can't mutate it.
        self.assertIsInstance(ALPHA_FORMATS, frozenset)


if __name__ == "__main__":
    unittest.main()
