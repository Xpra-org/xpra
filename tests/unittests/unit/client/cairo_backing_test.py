#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2024 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest


class TestParsePaddingColors(unittest.TestCase):

    def test_empty_string(self):
        from xpra.cairo.backing_base import parse_padding_colors
        r = parse_padding_colors("")
        assert r == (0.0, 0.0, 0.0), f"expected black, got {r}"

    def test_valid_colors(self):
        from xpra.cairo.backing_base import parse_padding_colors
        r = parse_padding_colors("1.0,0.5,0.0")
        assert len(r) == 3
        assert abs(r[0] - 1.0) < 0.001
        assert abs(r[1] - 0.5) < 0.001
        assert abs(r[2] - 0.0) < 0.001

    def test_spaces_trimmed(self):
        from xpra.cairo.backing_base import parse_padding_colors
        r = parse_padding_colors(" 0.2 , 0.4 , 0.6 ")
        assert abs(r[0] - 0.2) < 0.001
        assert abs(r[1] - 0.4) < 0.001
        assert abs(r[2] - 0.6) < 0.001

    def test_too_few_components_falls_back_to_black(self):
        from xpra.cairo.backing_base import parse_padding_colors
        r = parse_padding_colors("0.5,0.5")
        assert r == (0.0, 0.0, 0.0)

    def test_non_numeric_falls_back_to_black(self):
        from xpra.cairo.backing_base import parse_padding_colors
        r = parse_padding_colors("red,green,blue")
        assert r == (0.0, 0.0, 0.0)


class TestClamp(unittest.TestCase):

    def test_below_zero(self):
        from xpra.cairo.backing_base import clamp
        assert clamp(-1.0) == 0.0
        assert clamp(-0.001) == 0.0

    def test_above_one(self):
        from xpra.cairo.backing_base import clamp
        assert clamp(1.001) == 1.0
        assert clamp(100.0) == 1.0

    def test_boundary_values(self):
        from xpra.cairo.backing_base import clamp
        assert clamp(0.0) == 0.0
        assert clamp(1.0) == 1.0

    def test_midrange(self):
        from xpra.cairo.backing_base import clamp
        assert clamp(0.5) == 0.5
        assert clamp(0.9999) == 0.9999


class TestGetScalingFilter(unittest.TestCase):

    def test_nearest_env_override(self):
        from xpra.cairo.backing_base import get_scaling_filter
        from xpra.util.env import OSEnvContext
        from cairo import FILTER_NEAREST
        with OSEnvContext(XPRA_SCALING_FILTER="nearest"):
            f = get_scaling_filter("text", 2.0, 2.0)
            assert f == FILTER_NEAREST

    def test_bilinear_env_override(self):
        from xpra.cairo.backing_base import get_scaling_filter
        from xpra.util.env import OSEnvContext
        from cairo import FILTER_GOOD
        with OSEnvContext(XPRA_SCALING_FILTER="bilinear"):
            f = get_scaling_filter("text", 2.0, 2.0)
            assert f == FILTER_GOOD

    def test_text_integer_upscale_uses_nearest(self):
        from xpra.cairo.backing_base import get_scaling_filter
        from xpra.util.env import OSEnvContext
        from cairo import FILTER_NEAREST
        with OSEnvContext(XPRA_SCALING_FILTER=""):
            f = get_scaling_filter("text", 2.0, 2.0)
            assert f == FILTER_NEAREST

    def test_text_non_integer_scale_uses_best(self):
        from xpra.cairo.backing_base import get_scaling_filter
        from xpra.util.env import OSEnvContext
        from cairo import FILTER_BEST
        with OSEnvContext(XPRA_SCALING_FILTER=""):
            f = get_scaling_filter("text", 1.5, 1.5)
            assert f == FILTER_BEST

    def test_non_text_uses_good(self):
        from xpra.cairo.backing_base import get_scaling_filter
        from xpra.util.env import OSEnvContext
        from cairo import FILTER_GOOD
        with OSEnvContext(XPRA_SCALING_FILTER=""):
            f = get_scaling_filter("video", 1.5, 1.5)
            assert f == FILTER_GOOD
            f = get_scaling_filter("", 2.0, 2.0)
            assert f == FILTER_GOOD


class _TestBacking:
    """Concrete CairoBackingBase for testing — mixed in below after import."""
    RGB_MODES = ("BGRA", "BGRX", "BGR", "RGB", "RGBA", "RGBX")
    _do_paint_rgb_calls: list

    def _do_paint_rgb(self, fmt, alpha, img_data, x, y, w, h, rw, rh, rowstride, options) -> None:
        self._do_paint_rgb_calls.append((fmt, alpha, img_data, x, y, w, h, rw, rh, rowstride, options))

    def repaint(self, x, y, w, h) -> None:
        pass

    def update_fps_buffer(self, width, height, pixels) -> None:
        pass


def _make_backing(wid=1, alpha=True, w=100, h=100):
    """Create a ready-to-use _TestBacking instance."""
    from xpra.cairo.backing_base import CairoBackingBase

    class TBacking(_TestBacking, CairoBackingBase):
        pass

    b = TBacking(wid, alpha)
    b._do_paint_rgb_calls = []
    b.border = None
    b.init(w, h, w, h)
    return b


# ---------------------------------------------------------------------------
# cairo_paint_pointer_overlay
# ---------------------------------------------------------------------------

class TestCairoPaintPointerOverlay(unittest.TestCase):

    def _ctx(self, w=64, h=64):
        from cairo import ImageSurface, Context, Format
        return Context(ImageSurface(Format.ARGB32, w, h))

    def test_no_cursor_data_returns_early(self):
        from xpra.cairo.backing_base import cairo_paint_pointer_overlay
        from time import monotonic
        ctx = self._ctx()
        cairo_paint_pointer_overlay(ctx, None, 10, 10, monotonic())
        cairo_paint_pointer_overlay(ctx, (), 10, 10, monotonic())

    def test_make_image_surface_noop_returns_early(self):
        from xpra.common import noop
        from unittest.mock import patch
        from xpra.cairo.backing_base import cairo_paint_pointer_overlay
        from time import monotonic
        cursor_data = [None, None, None, 16, 16, 0, 0, None, b"\x00" * (16 * 16 * 4)]
        ctx = self._ctx()
        with patch("xpra.cairo.backing_base.make_image_surface", noop):
            cairo_paint_pointer_overlay(ctx, cursor_data, 10, 10, monotonic())

    def test_elapsed_too_large_returns_early(self):
        from xpra.cairo.backing_base import cairo_paint_pointer_overlay
        from time import monotonic
        cursor_data = [None, None, None, 16, 16, 0, 0, None, b"\x00" * (16 * 16 * 4)]
        ctx = self._ctx()
        old_start = monotonic() - 10
        cairo_paint_pointer_overlay(ctx, cursor_data, 10, 10, old_start)

    def test_normal_case_paints(self):
        from unittest.mock import patch
        from xpra.cairo.backing_base import cairo_paint_pointer_overlay
        from time import monotonic
        from cairo import ImageSurface, Format
        cw, ch = 16, 16
        pixels = b"\x80\x40\x20\xFF" * (cw * ch)
        cursor_data = [None, None, None, cw, ch, 2, 3, None, pixels]
        ctx = self._ctx(200, 200)
        fake_surface = ImageSurface(Format.ARGB32, cw, ch)
        with patch("xpra.cairo.backing_base.make_image_surface", return_value=fake_surface):
            cairo_paint_pointer_overlay(ctx, cursor_data, 20, 30, monotonic())


# ---------------------------------------------------------------------------
# cairo_draw_backing
# ---------------------------------------------------------------------------

class TestCairoDrawBacking(unittest.TestCase):

    def _make(self, w=64, h=64):
        from cairo import ImageSurface, Context, Format
        surface = ImageSurface(Format.ARGB32, w, h)
        ctx = Context(surface)
        return ctx, surface

    def test_sets_operator_source(self):
        from cairo import Operator
        from xpra.cairo.backing_base import cairo_draw_backing
        ctx, backing = self._make()
        cairo_draw_backing(ctx, backing)
        # smoke test: no exception, operator is SOURCE after the call
        assert ctx.get_operator() == Operator.SOURCE

    def test_with_scaling_filter(self):
        from cairo import FILTER_NEAREST
        from xpra.cairo.backing_base import cairo_draw_backing
        ctx, backing = self._make()
        cairo_draw_backing(ctx, backing, scaling_filter=FILTER_NEAREST)

    def test_without_filter(self):
        from xpra.cairo.backing_base import cairo_draw_backing
        ctx, backing = self._make()
        cairo_draw_backing(ctx, backing, scaling_filter=None)


# ---------------------------------------------------------------------------
# CairoBackingBase.__init__ and init
# ---------------------------------------------------------------------------

class TestCairoBackingBaseInit(unittest.TestCase):

    def test_initial_attributes(self):
        b = _make_backing()
        assert b.size == (100, 100)
        assert b.render_size == (100, 100)
        assert b.fps_image is None
        assert b.content_type == ""

    def test_init_creates_surface(self):
        b = _make_backing()
        assert b._backing is not None

    def test_init_skips_create_when_unchanged(self):
        from unittest.mock import patch
        b = _make_backing()
        with patch.object(b, "create_surface") as mock_cs:
            b.init(100, 100, 100, 100)
            mock_cs.assert_not_called()

    def test_init_recreates_on_size_change(self):
        from unittest.mock import patch
        b = _make_backing()
        with patch.object(b, "create_surface", return_value=None) as mock_cs:
            b.init(200, 200, 200, 200)
            mock_cs.assert_called_once()

    def test_wid_zero_alpha_false(self):
        b = _make_backing(wid=42, alpha=False)
        assert b.wid == 42
        assert not b._alpha_enabled


# ---------------------------------------------------------------------------
# create_surface and close
# ---------------------------------------------------------------------------

class TestCairoBackingBaseCreateSurface(unittest.TestCase):

    def test_creates_image_surface(self):
        from cairo import ImageSurface
        b = _make_backing()
        assert isinstance(b._backing, ImageSurface)
        assert b._backing.get_width() == 100
        assert b._backing.get_height() == 100

    def test_zero_size_returns_none(self):
        b = _make_backing()
        b.size = (0, 0)
        result = b.create_surface()
        assert result is None
        assert b._backing is None

    def test_close_finishes_backing(self):
        b = _make_backing()
        assert b._backing is not None
        b.close()
        assert b._backing is None

    def test_close_idempotent(self):
        b = _make_backing()
        b.close()
        b.close()  # should not raise

    def test_copy_old_backing_on_resize(self):
        b = _make_backing(w=50, h=50)
        b.size = (100, 100)
        b.render_size = (100, 100)
        cr = b.create_surface()
        assert cr is not None
        assert b._backing.get_width() == 100

    def test_create_surface_alpha_enabled(self):
        b = _make_backing(alpha=True)
        b.size = (32, 32)
        b.render_size = (32, 32)
        b.create_surface()
        assert b._backing is not None

    def test_create_surface_no_alpha(self):
        b = _make_backing(alpha=False)
        b.size = (32, 32)
        b.render_size = (32, 32)
        b.create_surface()
        assert b._backing is not None


# ---------------------------------------------------------------------------
# get_info
# ---------------------------------------------------------------------------

class TestCairoBackingBaseGetInfo(unittest.TestCase):

    def test_has_type_cairo(self):
        b = _make_backing()
        info = b.get_info()
        assert info.get("type") == "Cairo"

    def test_has_rgb_formats(self):
        b = _make_backing()
        info = b.get_info()
        assert "rgb-formats" in info

    def test_size_in_info(self):
        b = _make_backing(w=80, h=60)
        info = b.get_info()
        assert info.get("size") == (80, 60)


# ---------------------------------------------------------------------------
# cairo_paint_box and cairo_paint_from_source
# ---------------------------------------------------------------------------

class TestCairoPaintBox(unittest.TestCase):

    def test_strokes_rectangle(self):
        from cairo import ImageSurface, Context, Format
        b = _make_backing()
        surface = ImageSurface(Format.ARGB32, 200, 200)
        gc = Context(surface)
        b.cairo_paint_box(gc, "h264", 10, 10, 50, 50)

    def test_unknown_encoding(self):
        from cairo import ImageSurface, Context, Format
        b = _make_backing()
        surface = ImageSurface(Format.ARGB32, 100, 100)
        gc = Context(surface)
        b.cairo_paint_box(gc, "unknown_codec", 0, 0, 100, 100)


class TestCairoPaintFromSource(unittest.TestCase):

    def test_no_backing_returns_early(self):
        from cairo import ImageSurface, Format
        b = _make_backing()
        b._backing = None
        src = ImageSurface(Format.ARGB32, 20, 20)
        called = []
        b.cairo_paint_from_source(lambda gc, s, x, y: called.append(1),
                                  src, 0, 0, 20, 20, 20, 20, {})
        assert not called

    def test_basic_paint(self):
        from cairo import ImageSurface, Format
        b = _make_backing()
        src = ImageSurface(Format.ARGB32, 20, 20)
        b.cairo_paint_from_source(
            lambda gc, s, sx, sy: gc.set_source_surface(s, sx, sy),
            src, 0, 0, 20, 20, 20, 20, {}
        )

    def test_paint_with_scale(self):
        from cairo import ImageSurface, Format
        b = _make_backing()
        src = ImageSurface(Format.ARGB32, 20, 20)
        b.cairo_paint_from_source(
            lambda gc, s, sx, sy: gc.set_source_surface(s, sx, sy),
            src, 0, 0, 20, 20, 40, 40, {}
        )

    def test_paint_with_paint_box(self):
        from cairo import ImageSurface, Format
        from xpra.util.objects import typedict
        b = _make_backing()
        b.paint_box_line_width = 2
        src = ImageSurface(Format.ARGB32, 20, 20)
        opts = typedict({"encoding": "h264"})
        b.cairo_paint_from_source(
            lambda gc, s, sx, sy: gc.set_source_surface(s, sx, sy),
            src, 5, 5, 20, 20, 20, 20, opts
        )


class TestCairoPaintSurface(unittest.TestCase):

    def test_paints_surface(self):
        from cairo import ImageSurface, Format
        b = _make_backing()
        src = ImageSurface(Format.ARGB32, 30, 30)
        b.cairo_paint_surface(src, 0, 0, 30, 30, {})

    def test_paints_scaled(self):
        from cairo import ImageSurface, Format
        b = _make_backing()
        src = ImageSurface(Format.ARGB32, 30, 30)
        b.cairo_paint_surface(src, 0, 0, 60, 60, {})


# ---------------------------------------------------------------------------
# do_paint_rgb
# ---------------------------------------------------------------------------

class TestDoPaintRgb(unittest.TestCase):

    def _callbacks(self):
        results = []
        return results, [lambda s, m: results.append((s, m))]

    def test_skip_paint_false(self):
        from xpra.util.objects import typedict
        b = _make_backing()
        results, cbs = self._callbacks()
        b.do_paint_rgb(None, "", "BGRA", b"\x00" * 400, 0, 0, 10, 10, 10, 10, 40, typedict({"paint": False}), cbs)
        assert results and results[0][0] is True

    def test_no_backing_fires_error(self):
        from xpra.util.objects import typedict
        b = _make_backing()
        b._backing = None
        results, cbs = self._callbacks()
        b.do_paint_rgb(None, "", "BGRA", b"\x00" * 400, 0, 0, 10, 10, 10, 10, 40, typedict(), cbs)
        assert results and results[0][0] == -1

    def test_bgra_32bpp(self):
        from xpra.util.objects import typedict
        b = _make_backing()
        results, cbs = self._callbacks()
        b.do_paint_rgb(None, "", "BGRA", b"\x00" * 400, 0, 0, 10, 10, 10, 10, 40, typedict(), cbs)
        assert results and results[0][0] is True
        assert b._do_paint_rgb_calls

    def test_rgb_24bpp(self):
        from xpra.util.objects import typedict
        b = _make_backing()
        results, cbs = self._callbacks()
        b.do_paint_rgb(None, "", "RGB", b"\x00" * 300, 0, 0, 10, 10, 10, 10, 30, typedict(), cbs)
        assert results and results[0][0] is True

    def test_bgr565_16bpp(self):
        from xpra.util.objects import typedict
        b = _make_backing()
        results, cbs = self._callbacks()
        b.do_paint_rgb(None, "", "BGR565", b"\x00" * 200, 0, 0, 10, 10, 10, 10, 20, typedict(), cbs)
        assert results and results[0][0] is True

    def test_r210_30bpp(self):
        from xpra.util.objects import typedict
        b = _make_backing()
        results, cbs = self._callbacks()
        b.do_paint_rgb(None, "", "r210", b"\x00" * 400, 0, 0, 10, 10, 10, 10, 40, typedict(), cbs)
        assert results and results[0][0] is True

    def test_invalid_format_fires_error(self):
        from xpra.util.objects import typedict
        b = _make_backing()
        results, cbs = self._callbacks()
        # single char → bpp=8 → Format.INVALID
        b.do_paint_rgb(None, "", "X", b"\x00" * 100, 0, 0, 10, 10, 10, 10, 10, typedict(), cbs)
        assert results and results[0][0] is False


# ---------------------------------------------------------------------------
# do_paint_scroll
# ---------------------------------------------------------------------------

class TestDoPaintScroll(unittest.TestCase):

    def _callbacks(self):
        results = []
        return results, [lambda s, m="": results.append((s, m))]

    def test_no_backing_fires_error(self):
        b = _make_backing()
        b._backing = None
        results, cbs = self._callbacks()
        b.do_paint_scroll([(0, 0, 10, 10, 5, 5)], cbs)
        assert results and results[0][0] is False

    def test_scroll_copies_region(self):
        results, cbs = self._callbacks()
        b = _make_backing()
        b.do_paint_scroll([(0, 0, 50, 50, 5, 5)], cbs)
        assert results and results[0][0] is True

    def test_scroll_with_paint_box(self):
        results, cbs = self._callbacks()
        b = _make_backing()
        b.paint_box_line_width = 2
        b.do_paint_scroll([(0, 0, 50, 50, 5, 5)], cbs)
        assert results and results[0][0] is True


# ---------------------------------------------------------------------------
# paint_backing_offset_border and clip_to_backing
# ---------------------------------------------------------------------------

class TestPaintBackingOffsetBorder(unittest.TestCase):

    def _ctx(self, w=200, h=200):
        from cairo import ImageSurface, Context, Format
        return Context(ImageSurface(Format.ARGB32, w, h))

    def test_zero_offsets_noop(self):
        b = _make_backing()
        b.offsets = (0, 0, 0, 0)
        ctx = self._ctx()
        b.paint_backing_offset_border(ctx, 200, 200)

    def test_with_offsets_paints_padding(self):
        b = _make_backing()
        b.offsets = (10, 5, 10, 5)
        ctx = self._ctx()
        b.paint_backing_offset_border(ctx, 200, 200)


class TestClipToBacking(unittest.TestCase):

    def _ctx(self, w=200, h=200):
        from cairo import ImageSurface, Context, Format
        return Context(ImageSurface(Format.ARGB32, w, h))

    def test_zero_render_size_returns_false(self):
        b = _make_backing()
        b.render_size = (0, 0)
        ctx = self._ctx()
        result = b.clip_to_backing(ctx, 200, 200)
        assert result is False

    def test_matching_sizes_returns_true(self):
        b = _make_backing(w=100, h=100)
        b.offsets = (0, 0, 0, 0)
        ctx = self._ctx()
        result = b.clip_to_backing(ctx, 100, 100)
        assert result is True

    def test_different_sizes_scales(self):
        b = _make_backing(w=50, h=50)
        b.render_size = (100, 100)
        b.offsets = (0, 0, 0, 0)
        ctx = self._ctx(100, 100)
        result = b.clip_to_backing(ctx, 100, 100)
        assert result is True

    def test_with_offsets(self):
        b = _make_backing(w=100, h=100)
        b.offsets = (5, 5, 5, 5)
        ctx = self._ctx()
        result = b.clip_to_backing(ctx, 100, 100)
        assert result is True


# ---------------------------------------------------------------------------
# cairo_draw
# ---------------------------------------------------------------------------

class TestCairoDraw(unittest.TestCase):

    def _ctx(self, w=200, h=200):
        from cairo import ImageSurface, Context, Format
        return Context(ImageSurface(Format.ARGB32, w, h))

    def test_no_backing_returns_early(self):
        b = _make_backing()
        b._backing = None
        ctx = self._ctx()
        b.cairo_draw(ctx, 100, 100)

    def test_basic_draw(self):
        b = _make_backing(w=100, h=100)
        ctx = self._ctx()
        b.cairo_draw(ctx, 100, 100)

    def test_draw_with_scaling(self):
        b = _make_backing(w=50, h=50)
        b.render_size = (100, 100)
        ctx = self._ctx()
        b.cairo_draw(ctx, 100, 100)


# ---------------------------------------------------------------------------
# cairo_draw_pointer
# ---------------------------------------------------------------------------

class TestCairoDrawPointer(unittest.TestCase):

    def _ctx(self, w=200, h=200):
        from cairo import ImageSurface, Context, Format
        return Context(ImageSurface(Format.ARGB32, w, h))

    def test_no_overlay_noop(self):
        b = _make_backing()
        b.pointer_overlay = ()
        ctx = self._ctx()
        b.cairo_draw_pointer(ctx)

    def test_no_cursor_data_noop(self):
        from time import monotonic
        b = _make_backing()
        b.pointer_overlay = (0, 0, 10, 10, 5, monotonic())
        b.cursor_data = ()
        b.default_cursor_data = ()
        ctx = self._ctx()
        b.cairo_draw_pointer(ctx)

    def test_with_cursor_data_and_overlay(self):
        from unittest.mock import patch
        from time import monotonic
        from cairo import ImageSurface, Format
        b = _make_backing()
        cw, ch = 8, 8
        pixels = b"\x80\x40\x20\xFF" * (cw * ch)
        b.cursor_data = [None, None, None, cw, ch, 1, 1, None, pixels]
        b.pointer_overlay = (0, 0, 20, 20, 5, monotonic())
        ctx = self._ctx()
        fake_surface = ImageSurface(Format.ARGB32, cw, ch)
        with patch("xpra.cairo.backing_base.make_image_surface", return_value=fake_surface):
            b.cairo_draw_pointer(ctx)


# ---------------------------------------------------------------------------
# cairo_draw_border
# ---------------------------------------------------------------------------

class TestCairoDrawBorder(unittest.TestCase):

    def _ctx(self, w=200, h=200):
        from cairo import ImageSurface, Context, Format
        return Context(ImageSurface(Format.ARGB32, w, h))

    def test_none_border_noop(self):
        b = _make_backing()
        ctx = self._ctx()
        b.cairo_draw_border(ctx, None)

    def test_hidden_border_noop(self):
        from xpra.client.gui.window_border import WindowBorder
        b = _make_backing()
        ctx = self._ctx()
        border = WindowBorder(shown=False)
        b.cairo_draw_border(ctx, border)

    def test_shown_border_paints(self):
        from xpra.client.gui.window_border import WindowBorder
        b = _make_backing(w=100, h=100)
        ctx = self._ctx()
        border = WindowBorder(shown=True, red=1.0, green=0.0, blue=0.0, alpha=0.5, size=4)
        b.cairo_draw_border(ctx, border)

    def test_border_larger_than_backing(self):
        from xpra.client.gui.window_border import WindowBorder
        b = _make_backing(w=10, h=10)
        ctx = self._ctx(10, 10)
        border = WindowBorder(shown=True, size=20)
        b.cairo_draw_border(ctx, border)


# ---------------------------------------------------------------------------
# Alert methods
# ---------------------------------------------------------------------------

class TestDrawAlertShade(unittest.TestCase):

    def _ctx(self, w=200, h=200):
        from cairo import ImageSurface, Context, Format
        return Context(ImageSurface(Format.ARGB32, w, h))

    def test_default_shade(self):
        b = _make_backing(w=100, h=100)
        ctx = self._ctx()
        b.draw_alert_shade(ctx)

    def test_custom_shade(self):
        b = _make_backing(w=100, h=100)
        ctx = self._ctx()
        b.draw_alert_shade(ctx, shade=0.8)


class TestDrawAlertSpinner(unittest.TestCase):

    def _ctx(self, w=200, h=200):
        from cairo import ImageSurface, Context, Format
        return Context(ImageSurface(Format.ARGB32, w, h))

    def test_default_spinner(self):
        b = _make_backing(w=200, h=200)
        ctx = self._ctx()
        b.draw_alert_spinner(ctx)

    def test_small_spinner(self):
        b = _make_backing(w=200, h=200)
        ctx = self._ctx()
        b.draw_alert_spinner(ctx, outer_pct=40)

    def test_big_spinner(self):
        b = _make_backing(w=200, h=200)
        ctx = self._ctx()
        b.draw_alert_spinner(ctx, outer_pct=90)


class TestGetAlertImage(unittest.TestCase):

    def test_returns_tuple(self):
        from xpra.cairo.backing_base import CairoBackingBase
        # reset cached value to force re-evaluation
        CairoBackingBase.alert_image = ()
        result = CairoBackingBase.get_alert_image()
        assert isinstance(result, tuple)

    def test_cached_on_second_call(self):
        from xpra.cairo.backing_base import CairoBackingBase
        r1 = CairoBackingBase.get_alert_image()
        r2 = CairoBackingBase.get_alert_image()
        assert r1 is r2


class TestDrawAlertIcon(unittest.TestCase):

    def _ctx(self, w=200, h=200):
        from cairo import ImageSurface, Context, Format
        return Context(ImageSurface(Format.ARGB32, w, h))

    def test_no_image_noop(self):
        from unittest.mock import patch
        from xpra.cairo.backing_base import CairoBackingBase
        b = _make_backing()
        ctx = self._ctx()
        with patch.object(CairoBackingBase, "get_alert_image", staticmethod(lambda: (0, 0, None))):
            b.draw_alert_icon(ctx)

    def test_with_image(self):
        from unittest.mock import patch
        from cairo import ImageSurface, Format
        from xpra.cairo.backing_base import CairoBackingBase
        b = _make_backing(w=100, h=100)
        ctx = self._ctx()
        fake_img = ImageSurface(Format.ARGB32, 32, 32)
        with patch.object(CairoBackingBase, "get_alert_image", staticmethod(lambda: (32, 32, fake_img))):
            b.draw_alert_icon(ctx)


class TestCairoDrawAlert(unittest.TestCase):

    def _ctx(self, w=200, h=200):
        from cairo import ImageSurface, Context, Format
        return Context(ImageSurface(Format.ARGB32, w, h))

    def test_no_alert_state_noop(self):
        b = _make_backing()
        b.alert_state = False
        ctx = self._ctx()
        b.cairo_draw_alert(ctx)

    def test_shade_mode(self):
        from xpra.util.env import OSEnvContext
        b = _make_backing(w=100, h=100)
        b.alert_state = True
        ctx = self._ctx()
        with OSEnvContext(XPRA_ALERT_MODE="shade"):
            from xpra.client.gui.window import backing as backing_mod
            orig = backing_mod.ALERT_MODE
            backing_mod.ALERT_MODE = ["shade"]
            try:
                b.cairo_draw_alert(ctx)
            finally:
                backing_mod.ALERT_MODE = orig

    def test_spinner_mode(self):
        b = _make_backing(w=200, h=200)
        b.alert_state = True
        ctx = self._ctx()
        from xpra.client.gui.window import backing as backing_mod
        orig = backing_mod.ALERT_MODE
        backing_mod.ALERT_MODE = ["spinner"]
        try:
            b.cairo_draw_alert(ctx)
        finally:
            backing_mod.ALERT_MODE = orig

    def test_icon_mode_no_image(self):
        from unittest.mock import patch
        from xpra.cairo.backing_base import CairoBackingBase
        from xpra.client.gui.window import backing as backing_mod
        b = _make_backing(w=100, h=100)
        b.alert_state = True
        ctx = self._ctx()
        orig = backing_mod.ALERT_MODE
        backing_mod.ALERT_MODE = ["icon"]
        try:
            with patch.object(CairoBackingBase, "get_alert_image", staticmethod(lambda: (0, 0, None))):
                b.cairo_draw_alert(ctx)
        finally:
            backing_mod.ALERT_MODE = orig


def main():
    unittest.main()


if __name__ == '__main__':
    main()
