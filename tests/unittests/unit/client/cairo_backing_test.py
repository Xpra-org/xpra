#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys
import unittest
from time import monotonic
from types import SimpleNamespace
from unittest.mock import patch

from cairo import Context, ImageSurface, FORMAT_ARGB32, FORMAT_RGB24, OPERATOR_SOURCE

from xpra.client.gtk3.cairo_backing_base import CairoBackingBase, cairo_paint_pointer_overlay
from xpra.util import typedict


class _TestBacking(CairoBackingBase):

    def __init__(self, alpha=True):
        self._alpha_enabled = alpha
        self.paint_calls = []

    def _do_paint_rgb(self, *args) -> bool:
        self.paint_calls.append(args)
        return True


class TestPaintRgb32(unittest.TestCase):

    @staticmethod
    def paint_format(rgb_format: str, alpha=True):
        backing = _TestBacking(alpha)
        options = typedict({"rgb_format": rgb_format})
        assert backing._do_paint_rgb32(b"\0" * 400, 0, 0, 10, 10, 10, 10, 40, options)
        assert backing.paint_calls
        return backing.paint_calls[0][:2]

    def test_padding_formats_never_use_argb32(self):
        for rgb_format in ("BGRX", "RGBX"):
            fmt, _alpha = self.paint_format(rgb_format)
            assert fmt == FORMAT_RGB24, f"{rgb_format} should be painted as RGB24, not {fmt}"

    def test_alpha_formats_use_argb32(self):
        for rgb_format in ("BGRA", "RGBA"):
            fmt, _alpha = self.paint_format(rgb_format)
            assert fmt == FORMAT_ARGB32, f"{rgb_format} should be painted as ARGB32, not {fmt}"

    def test_alpha_formats_without_window_alpha(self):
        for rgb_format in ("BGRA", "RGBA"):
            fmt, alpha = self.paint_format(rgb_format, alpha=False)
            assert fmt == FORMAT_RGB24, f"{rgb_format} should be painted as RGB24, not {fmt}"
            assert alpha is False


class TestCairoPaintPointerOverlay(unittest.TestCase):

    def test_preserves_context_state(self):
        pixels = b"\x80\x40\x20\xff" * (16 * 16)
        cursor_data = [None, None, None, 16, 16, 2, 3, None, pixels]
        context = Context(ImageSurface(FORMAT_ARGB32, 200, 200))
        context.translate(3, 4)
        context.set_operator(OPERATOR_SOURCE)
        matrix = context.get_matrix()
        source = context.get_source().get_rgba()
        # Pixel conversion is independent of the context state being tested.
        argb = SimpleNamespace(unpremultiply_argb=lambda data: data)
        with patch.dict(sys.modules, {"xpra.codecs.argb.argb": argb}):
            cairo_paint_pointer_overlay(context, cursor_data, 20, 30, monotonic())
        self.assertEqual(context.get_matrix(), matrix)
        self.assertEqual(context.get_operator(), OPERATOR_SOURCE)
        self.assertEqual(context.get_source().get_rgba(), source)


if __name__ == "__main__":
    unittest.main()
