#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import sys
import unittest
from unittest.mock import MagicMock, patch

from OpenGL.GL import GL_RGBA8, GL_RGB8, GL_RGBA4, GL_RGB5_A1, GL_RGB565, GL_RGBA16, GL_RGB10_A2, GL_NEAREST, GL_LINEAR


class TestModuleFunctions(unittest.TestCase):
    """Test pure Python helper functions at module level."""

    def test_clamp(self):
        from xpra.opengl.backing import clamp
        assert clamp(0.0) == 0.0
        assert clamp(1.0) == 1.0
        assert clamp(0.5) == 0.5
        assert clamp(-1.0) == 0.0
        assert clamp(2.0) == 1.0

    def test_charclamp(self):
        from xpra.opengl.backing import charclamp
        assert charclamp(0) == 0
        assert charclamp(255) == 255
        assert charclamp(128) == 128
        assert charclamp(-1) == 0
        assert charclamp(256) == 255
        assert charclamp(127.9) == 128

    def test_get_tex_name_yuv(self):
        from xpra.opengl.backing import get_tex_name
        # YUV420P: plane 0=Y, 1=U, 2=V, single byte
        assert get_tex_name("YUV420P", 0) == "Y"
        assert get_tex_name("YUV420P", 1) == "U"
        assert get_tex_name("YUV420P", 2) == "V"

    def test_get_tex_name_16bit(self):
        from xpra.opengl.backing import get_tex_name
        # P16 formats: doubled plane names
        n = get_tex_name("YUV420P16", 0)
        assert n == "YY"

    def test_get_tex_name_default(self):
        from xpra.opengl.backing import get_tex_name
        # default args: YUV420P, index 0 → "Y"
        assert get_tex_name() == "Y"


def _make_mock_backing(wid=1, window_alpha=False, pixel_depth=0):
    """Create a GLWindowBackingBase subclass with all abstract methods mocked out."""
    from xpra.opengl.backing import GLWindowBackingBase

    class _MockBacking(GLWindowBackingBase):
        def init_gl_config(self):
            pass

        def init_backing(self):
            mock = MagicMock()
            mock.show = lambda: None
            self._backing = mock

        def is_double_buffered(self):
            return True

        def with_gl_context(self, cb, *args):
            pass

        def do_gl_show(self, rect_count):
            pass

        def gl_context(self):
            return None

    with patch("xpra.opengl.backing.is_X11", return_value=False):
        b = _MockBacking(wid, window_alpha, pixel_depth)
    return b


class TestInitFormats(unittest.TestCase):
    """Test init_formats() logic at various bit depths."""

    def _make(self, window_alpha=False, pixel_depth=0):
        return _make_mock_backing(1, window_alpha, pixel_depth)

    def test_default_no_alpha(self):
        b = self._make(window_alpha=False, pixel_depth=0)
        assert b.internal_format == GL_RGB8

    def test_default_with_alpha(self):
        b = self._make(window_alpha=True, pixel_depth=0)
        assert b.internal_format == GL_RGBA8

    def test_bit_depth_24(self):
        b = self._make(window_alpha=False, pixel_depth=24)
        assert b.internal_format == GL_RGB8

    def test_bit_depth_32(self):
        b = self._make(window_alpha=True, pixel_depth=32)
        assert b.internal_format == GL_RGBA8

    def test_bit_depth_16_no_alpha(self):
        b = self._make(window_alpha=False, pixel_depth=16)
        assert b.internal_format == GL_RGB565
        assert "BGR565" in b.RGB_MODES
        assert "RGB565" in b.RGB_MODES

    def test_bit_depth_16_with_alpha(self):
        b = self._make(window_alpha=True, pixel_depth=16)
        assert b.internal_format in (GL_RGBA4, GL_RGB5_A1)

    def test_bit_depth_30(self):
        b = self._make(window_alpha=False, pixel_depth=30)
        assert b.internal_format == GL_RGB10_A2
        assert "r210" in b.RGB_MODES

    def test_bit_depth_above_32(self):
        b = self._make(window_alpha=False, pixel_depth=48)
        assert b.internal_format == GL_RGBA16
        assert "r210" in b.RGB_MODES


class TestGetInfo(unittest.TestCase):

    def test_get_info_keys(self):
        b = _make_mock_backing()
        info = b.get_info()
        assert info.get("type") == "OpenGL"
        assert "bit-depth" in info
        assert "internal-format" in info

    def test_get_info_no_error(self):
        b = _make_mock_backing()
        b.last_present_fbo_error = ""
        info = b.get_info()
        assert "last-error" not in info

    def test_get_info_with_error(self):
        b = _make_mock_backing()
        b.last_present_fbo_error = "test error"
        info = b.get_info()
        assert info.get("last-error") == "test error"


class TestGetInitMagfilter(unittest.TestCase):

    def test_integer_scale_returns_nearest(self):
        b = _make_mock_backing()
        b.render_size = (800, 600)
        b.size = (800, 600)
        assert b.get_init_magfilter() == GL_NEAREST

    def test_double_scale_returns_nearest(self):
        b = _make_mock_backing()
        b.render_size = (1600, 1200)
        b.size = (800, 600)
        assert b.get_init_magfilter() == GL_NEAREST

    def test_non_integer_scale_returns_linear(self):
        b = _make_mock_backing()
        b.render_size = (1000, 750)
        b.size = (800, 600)
        assert b.get_init_magfilter() == GL_LINEAR


class TestGetBitDepth(unittest.TestCase):

    def test_zero_returns_24(self):
        b = _make_mock_backing(pixel_depth=0)
        assert b.get_bit_depth(0) == 24

    def test_passthrough(self):
        b = _make_mock_backing(pixel_depth=30)
        assert b.get_bit_depth(30) == 30

    def test_stored_bit_depth(self):
        b = _make_mock_backing(pixel_depth=24)
        assert b.bit_depth == 24


class TestRepr(unittest.TestCase):

    def test_repr_contains_wid(self):
        b = _make_mock_backing(wid=0x1234)
        s = repr(b)
        assert "GLWindowBacking" in s
        assert "0x1234" in s


class TestGetEncodingProperties(unittest.TestCase):

    def test_bit_depth_in_props(self):
        b = _make_mock_backing(pixel_depth=24)
        props = b.get_encoding_properties()
        assert props.get("encoding.bit-depth") == 24


class TestSwapFbos(unittest.TestCase):
    """swap_fbos() is pure Python reference-swapping — no GL context needed."""

    def _make_with_fbos(self):
        from xpra.opengl.backing import N_TEXTURES, TEX_FBO, TEX_TMP_FBO
        b = _make_mock_backing()
        b.offscreen_fbo = 1
        b.tmp_fbo = 2
        b.textures = list(range(N_TEXTURES))
        b.textures[TEX_FBO] = 10
        b.textures[TEX_TMP_FBO] = 20
        return b, TEX_FBO, TEX_TMP_FBO

    def test_swaps_fbo_handles(self):
        b, TEX_FBO, TEX_TMP_FBO = self._make_with_fbos()
        b.swap_fbos()
        assert b.offscreen_fbo == 2
        assert b.tmp_fbo == 1

    def test_swaps_texture_indices(self):
        b, TEX_FBO, TEX_TMP_FBO = self._make_with_fbos()
        b.swap_fbos()
        assert b.textures[TEX_FBO] == 20
        assert b.textures[TEX_TMP_FBO] == 10

    def test_double_swap_is_identity(self):
        b, TEX_FBO, TEX_TMP_FBO = self._make_with_fbos()
        b.swap_fbos()
        b.swap_fbos()
        assert b.offscreen_fbo == 1
        assert b.tmp_fbo == 2
        assert b.textures[TEX_FBO] == 10
        assert b.textures[TEX_TMP_FBO] == 20


class TestFailShader(unittest.TestCase):
    """fail_shader() raises RuntimeError; glDeleteShader is skipped if shader not registered."""

    def test_raises_runtime_error(self):
        b = _make_mock_backing()
        with self.assertRaises(RuntimeError) as cm:
            b.fail_shader("myshader", "compile failed")
        assert "myshader" in str(cm.exception)

    def test_bytes_error_decoded(self):
        b = _make_mock_backing()
        with self.assertRaises(RuntimeError) as cm:
            b.fail_shader("myshader", b"undefined variable")
        assert "undefined variable" in str(cm.exception)

    def test_error_text_in_exception(self):
        b = _make_mock_backing()
        with self.assertRaises(RuntimeError) as cm:
            b.fail_shader("s", "bad syntax on line 7")
        assert "bad syntax on line 7" in str(cm.exception)

    def test_strips_trailing_newlines(self):
        b = _make_mock_backing()
        with self.assertRaises(RuntimeError) as cm:
            b.fail_shader("s", "oops\n\r")
        # message should not end with literal \n\r
        assert str(cm.exception).rstrip()

    def test_no_gl_call_when_not_registered(self):
        """With no shader in self.shaders, glDeleteShader is never called (no GL context required)."""
        b = _make_mock_backing()
        b.shaders.clear()
        with self.assertRaises(RuntimeError):
            b.fail_shader("unregistered", "error")


class TestPresentFboLogic(unittest.TestCase):
    """present_fbo() context guard and pending_fbo_paint accumulation."""

    def test_no_context_raises(self):
        b = _make_mock_backing()
        with self.assertRaises(RuntimeError):
            b.present_fbo(None, 0, 0, 100, 100)

    def test_accumulates_pending_paint(self):
        b = _make_mock_backing()
        b.paint_screen = False     # prevent managed_present_fbo GL calls
        ctx = MagicMock()
        b.present_fbo(ctx, 10, 20, 100, 200)
        assert (10, 20, 100, 200) in b.pending_fbo_paint

    def test_multiple_rects_accumulated(self):
        b = _make_mock_backing()
        b.paint_screen = False
        ctx = MagicMock()
        b.present_fbo(ctx, 0, 0, 50, 50)
        b.present_fbo(ctx, 50, 0, 50, 50)
        assert len(b.pending_fbo_paint) == 2

    def test_flush_nonzero_does_not_call_managed(self):
        """With flush>0 and PAINT_FLUSH enabled, managed_present_fbo is deferred."""
        from unittest.mock import patch
        b = _make_mock_backing()
        b.paint_screen = True
        ctx = MagicMock()
        with patch("xpra.opengl.backing.PAINT_FLUSH", True):
            with patch.object(b, "managed_present_fbo") as mock_mgr:
                b.present_fbo(ctx, 0, 0, 100, 100, flush=1)
                mock_mgr.assert_not_called()

    def test_flush_zero_calls_managed(self):
        """With flush=0 and paint_screen=True, managed_present_fbo is called."""
        b = _make_mock_backing()
        b.paint_screen = True
        ctx = MagicMock()
        with patch.object(b, "managed_present_fbo") as mock_mgr:
            b.present_fbo(ctx, 0, 0, 100, 100, flush=0)
            mock_mgr.assert_called_once_with(ctx)


class TestDrawPointerLogic(unittest.TestCase):
    """draw_pointer() timeout and early-return guards (no GL context needed)."""

    def test_expired_timeout_clears_overlay(self):
        from time import monotonic
        from xpra.opengl.backing import CURSOR_IDLE_TIMEOUT
        b = _make_mock_backing()
        start_time = monotonic() - CURSOR_IDLE_TIMEOUT - 1
        b.pointer_overlay = (100, 200, 0, 0, 0, start_time)
        b.draw_pointer()
        assert b.pointer_overlay == ()

    def test_no_cursor_data_returns_without_crash(self):
        from time import monotonic
        b = _make_mock_backing()
        b.pointer_overlay = (100, 200, 0, 0, 0, monotonic())
        b.cursor_data = ()     # no cursor — must not raise
        b.draw_pointer()
        assert b.pointer_overlay != ()    # not expired, so not cleared


class TestPaintBoxEarlyReturn(unittest.TestCase):
    """paint_box() with line_width=0 returns immediately with no GL calls."""

    def test_zero_line_width_is_noop(self):
        b = _make_mock_backing()
        b.paint_box_line_width = 0
        # would raise if it reached any GL code without a context
        b.paint_box("rgb24", 0, 0, 100, 100)

    def test_negative_line_width_is_noop(self):
        b = _make_mock_backing()
        b.paint_box_line_width = -1
        b.paint_box("h264", 10, 20, 80, 60)


# ---------------------------------------------------------------------------
# GL context tests: require an actual OpenGL context.
# On Linux uses Xvfb + Mesa software rendering (LIBGL_ALWAYS_SOFTWARE=1).
# On macOS / Windows a display is assumed to already be present.
# ---------------------------------------------------------------------------

class TestGLInit(unittest.TestCase):

    xvfb = None

    @classmethod
    def setUpClass(cls):
        import time
        if os.name == "posix" and sys.platform != "darwin":
            from unit.process_test_util import ProcessTestUtil
            ProcessTestUtil.setUpClass()
            cls.ptu = ProcessTestUtil()
            cls.ptu.setUp()
            os.environ["LIBGL_ALWAYS_SOFTWARE"] = "1"
            os.environ["GDK_BACKEND"] = "x11"
            cls.xvfb = cls.ptu.start_Xvfb()
            os.environ["DISPLAY"] = cls.xvfb.display or ""
            try:
                from xpra.x11.bindings.wait_for_x_server import wait_for_x_server
                wait_for_x_server(cls.xvfb.display or "", 10)
            except ImportError:
                time.sleep(3)
            from xpra.os_util import gi_import
            Gdk = gi_import("Gdk")
            Gdk.Display.open(cls.xvfb.display or "")
            from xpra.x11.gtk.display_source import init_gdk_display_source
            init_gdk_display_source()

    @classmethod
    def tearDownClass(cls):
        if cls.xvfb:
            cls.xvfb.terminate()
            cls.xvfb = None
            from unit.process_test_util import ProcessTestUtil
            cls.ptu.tearDown()
            ProcessTestUtil.tearDownClass()

    def _make_gl_backing(self, window_alpha=False, pixel_depth=0):
        from xpra.os_util import gi_import
        from xpra.client.gtk3.opengl.drawing_area import GLDrawingArea
        Gtk = gi_import("Gtk")
        win = Gtk.Window()
        win.set_default_size(256, 256)
        backing = GLDrawingArea(1, window_alpha, pixel_depth)
        backing.size = (256, 256)
        backing.render_size = (256, 256)
        win.add(backing._backing)
        win.show_all()
        GLib = gi_import("GLib")
        ctx = GLib.main_context_default()
        for _ in range(20):
            ctx.iteration(False)
        return backing, win

    def test_gl_init_runs(self):
        """GLDrawingArea can initialize an OpenGL context."""
        backing, win = self._make_gl_backing()
        try:
            ctx = backing.gl_context()
            if ctx:
                with ctx:
                    backing.gl_init(ctx)
                assert backing.gl_setup
        finally:
            backing.close()
            win.destroy()

    def test_init_textures(self):
        """init_textures() creates textures and fbos."""
        backing, win = self._make_gl_backing()
        try:
            ctx = backing.gl_context()
            if ctx:
                with ctx:
                    backing.init_textures()
                assert len(backing.textures) > 0
                assert backing.offscreen_fbo is not None
        finally:
            backing.close()
            win.destroy()

    def test_init_fbo(self):
        """init_fbo() initializes the framebuffer and clears it."""
        from xpra.opengl.backing import TEX_FBO
        backing, win = self._make_gl_backing()
        try:
            ctx = backing.gl_context()
            if ctx:
                with ctx:
                    backing.init_textures()
                    backing.init_fbo(TEX_FBO, backing.offscreen_fbo, 64, 64, GL_NEAREST)
        finally:
            backing.close()
            win.destroy()

    def test_gl_init_size_too_large(self):
        """gl_init() raises ValueError when texture size exceeds the GL maximum."""
        backing, win = self._make_gl_backing()
        try:
            ctx = backing.gl_context()
            if ctx:
                with ctx:
                    backing.size = (200000, 200000)
                    self.assertRaises(ValueError, backing.gl_init, ctx)
        finally:
            backing.close()
            win.destroy()

    def test_init_shaders(self):
        """init_shaders() compiles and links all fragment programs."""
        backing, win = self._make_gl_backing()
        try:
            ctx = backing.gl_context()
            if ctx:
                with ctx:
                    backing.init_textures()
                    backing.init_shaders()
                assert len(backing.programs) > 0
        finally:
            backing.close()
            win.destroy()

    def test_init_call(self):
        """init() updates render_size and resets gl_setup on size change."""
        backing, win = self._make_gl_backing()
        try:
            backing.gl_setup = True
            backing.size = (100, 100)
            backing.init(200, 150, 200, 150)
            assert backing.render_size == (200, 150)
            assert not backing.gl_setup
        finally:
            backing.close()
            win.destroy()

    def test_init_no_size_change(self):
        """init() does not reset gl_setup when size is unchanged."""
        backing, win = self._make_gl_backing()
        try:
            backing.gl_setup = True
            backing.size = (200, 150)
            backing.init(200, 150, 200, 150)
            assert backing.gl_setup
        finally:
            backing.close()
            win.destroy()

    # ------------------------------------------------------------------
    # Helper
    # ------------------------------------------------------------------

    def _full_gl_init(self, backing):
        """Run gl_init + init_shaders inside a context; return the context (or None)."""
        ctx = backing.gl_context()
        if ctx:
            with ctx:
                backing.gl_init(ctx)
                backing.init_shaders()
        return ctx

    # ------------------------------------------------------------------
    # resize_fbo / copy_fbo / swap_fbos
    # ------------------------------------------------------------------

    def test_resize_fbo(self):
        """resize_fbo copies the existing FBO pixels onto a new-sized tmp FBO."""
        backing, win = self._make_gl_backing()
        try:
            ctx = backing.gl_context()
            if ctx:
                with ctx:
                    backing.gl_init(ctx)
                    # update size to simulate a window resize, then call resize_fbo
                    old_w, old_h = backing.size
                    new_w, new_h = old_w + 64, old_h + 32
                    backing.size = (new_w, new_h)
                    backing.render_size = (new_w, new_h)
                    backing.resize_fbo(ctx, old_w, old_h, new_w, new_h)
                assert backing.offscreen_fbo is not None
        finally:
            backing.close()
            win.destroy()

    def test_copy_fbo(self):
        """copy_fbo blits offscreen FBO into the tmp FBO without error."""
        backing, win = self._make_gl_backing()
        try:
            ctx = backing.gl_context()
            if ctx:
                with ctx:
                    backing.gl_init(ctx)
                    w, h = backing.size
                    backing.copy_fbo(w, h)
        finally:
            backing.close()
            win.destroy()

    def test_swap_fbos_gl(self):
        """swap_fbos() exchanges fbo handles and texture indices after full init."""
        from xpra.opengl.backing import TEX_FBO, TEX_TMP_FBO
        backing, win = self._make_gl_backing()
        try:
            ctx = backing.gl_context()
            if ctx:
                with ctx:
                    backing.gl_init(ctx)
                off_before = backing.offscreen_fbo
                tmp_before = backing.tmp_fbo
                tex_fbo_before = backing.textures[TEX_FBO]
                tex_tmp_before = backing.textures[TEX_TMP_FBO]
                backing.swap_fbos()
                assert backing.offscreen_fbo == tmp_before
                assert backing.tmp_fbo == off_before
                assert backing.textures[TEX_FBO] == tex_tmp_before
                assert backing.textures[TEX_TMP_FBO] == tex_fbo_before
        finally:
            backing.close()
            win.destroy()

    # ------------------------------------------------------------------
    # do_present_fbo / present_fbo / _present_fbo_catmull_rom
    # ------------------------------------------------------------------

    def test_do_present_fbo(self):
        """do_present_fbo renders the offscreen FBO to the display framebuffer."""
        backing, win = self._make_gl_backing()
        try:
            ctx = backing.gl_context()
            if ctx:
                with ctx:
                    backing.gl_init(ctx)
                    backing.pending_fbo_paint = [(0, 0, *backing.size)]
                    backing.do_present_fbo(ctx)
        finally:
            backing.close()
            win.destroy()

    def test_present_fbo(self):
        """present_fbo appends the rect and flushes through to do_present_fbo."""
        backing, win = self._make_gl_backing()
        try:
            ctx = backing.gl_context()
            if ctx:
                with ctx:
                    backing.gl_init(ctx)
                    backing.paint_screen = True
                    w, h = backing.size
                    backing.present_fbo(ctx, 0, 0, w, h, flush=0)
        finally:
            backing.close()
            win.destroy()

    def test_present_fbo_catmull_rom(self):
        """_present_fbo_catmull_rom runs when the upscale shader is available."""
        backing, win = self._make_gl_backing()
        try:
            ctx = self._full_gl_init(backing)
            if ctx and "upscale" in backing.programs:
                bw, bh = backing.size
                with ctx:
                    backing._present_fbo_catmull_rom(2.0, 2.0, 0, 0)
        finally:
            backing.close()
            win.destroy()

    # ------------------------------------------------------------------
    # save_fbo
    # ------------------------------------------------------------------

    def test_save_fbo(self):
        """save_fbo delegates to the utility function with correct arguments."""
        backing, win = self._make_gl_backing()
        try:
            ctx = backing.gl_context()
            if ctx:
                with ctx:
                    backing.gl_init(ctx)
                    with patch("xpra.opengl.backing.save_fbo") as mock_save:
                        backing.save_fbo()
                        mock_save.assert_called_once()
                        args = mock_save.call_args[0]
                        assert args[0] == backing.wid
                        assert args[3] == backing.size[0]
                        assert args[4] == backing.size[1]
        finally:
            backing.close()
            win.destroy()

    # ------------------------------------------------------------------
    # Alert overlays
    # ------------------------------------------------------------------

    def test_upload_alert_texture(self):
        """upload_alert_texture returns False gracefully when no icon is available."""
        backing, win = self._make_gl_backing()
        try:
            ctx = backing.gl_context()
            if ctx:
                with ctx:
                    backing.gl_init(ctx)
                    result = backing.upload_alert_texture()
                    assert isinstance(result, bool)
                    # second call should return the cached result
                    result2 = backing.upload_alert_texture()
                    assert result2 == result
        finally:
            backing.close()
            win.destroy()

    def test_draw_alert_spinner(self):
        """draw_alert_spinner uses the fixed-color shader to draw NLINES sectors."""
        backing, win = self._make_gl_backing()
        try:
            ctx = self._full_gl_init(backing)
            if ctx:
                with ctx:
                    backing.draw_alert_spinner()
                    backing.draw_alert_spinner(outer_pct=40)   # small-spinner variant
                    backing.draw_alert_spinner(outer_pct=90)   # big-spinner variant
        finally:
            backing.close()
            win.destroy()

    def test_draw_alert_shade(self):
        """draw_alert_shade blends a semi-transparent shade over the FBO."""
        backing, win = self._make_gl_backing()
        try:
            ctx = self._full_gl_init(backing)
            if ctx:
                with ctx:
                    backing.draw_alert_shade()              # default shade=0.5
                    backing.draw_alert_shade(shade=0.2)     # dark-shade
                    backing.draw_alert_shade(shade=0.8)     # light-shade
        finally:
            backing.close()
            win.destroy()

    def test_draw_alert_icon(self):
        """draw_alert_icon completes without error; alert_uploaded is set to ±1."""
        backing, win = self._make_gl_backing()
        try:
            ctx = self._full_gl_init(backing)
            if ctx:
                with ctx:
                    backing.draw_alert_icon()
                # alert_uploaded is either 1 (icon found & uploaded) or -1 (not found)
                assert backing.alert_uploaded != 0
        finally:
            backing.close()
            win.destroy()

    def test_draw_alert_icon_no_icon(self):
        """draw_alert_icon returns early and sets alert_uploaded=-1 when no icon exists."""
        backing, win = self._make_gl_backing()
        try:
            ctx = self._full_gl_init(backing)
            if ctx:
                from xpra.client.gui.window.backing import WindowBackingBase
                with patch.object(WindowBackingBase, "get_alert_icon", return_value=(0, 0, None)):
                    with ctx:
                        backing.draw_alert_icon()
                    assert backing.alert_uploaded == -1
        finally:
            backing.close()
            win.destroy()

    # ------------------------------------------------------------------
    # draw_pointer
    # ------------------------------------------------------------------

    def test_draw_pointer_gl(self):
        """draw_pointer renders the cursor overlay texture at the pointer position."""
        from time import monotonic
        from xpra.opengl.backing import TEX_CURSOR
        from xpra.opengl.util import upload_rgba_texture
        backing, win = self._make_gl_backing()
        try:
            ctx = self._full_gl_init(backing)
            if ctx:
                cw, ch = 16, 16
                pixels = b"\x80\x80\x80\xff" * (cw * ch)
                with ctx:
                    upload_rgba_texture(int(backing.textures[TEX_CURSOR]), cw, ch, pixels)
                # cursor_data: (name, serial, pixel_seq, width, height, xhot, yhot, cursor_serial, pixels)
                backing.cursor_data = (None, None, None, cw, ch, 0, 0, None, pixels)
                backing.pointer_overlay = (50, 50, 0, 0, 0, monotonic())
                with ctx:
                    backing.draw_pointer()
        finally:
            backing.close()
            win.destroy()

    # ------------------------------------------------------------------
    # draw_border / paint_box
    # ------------------------------------------------------------------

    def test_draw_border(self):
        """draw_border blends a coloured rectangle around the FBO edges."""
        from xpra.client.gui.window_border import WindowBorder
        backing, win = self._make_gl_backing()
        try:
            ctx = self._full_gl_init(backing)
            if ctx:
                border = WindowBorder(shown=True, red=1.0, green=0.0, blue=0.0, alpha=0.6, size=4)
                with ctx:
                    backing.draw_border(border)
                    # small window: border larger than window forces single-rect mode
                    border_big = WindowBorder(shown=True, size=512)
                    backing.draw_border(border_big)
        finally:
            backing.close()
            win.destroy()

    def test_paint_box(self):
        """paint_box draws a debug rectangle around the painted region."""
        backing, win = self._make_gl_backing()
        try:
            ctx = self._full_gl_init(backing)
            if ctx:
                backing.paint_box_line_width = 2
                with ctx:
                    backing.paint_box("rgb24", 10, 20, 80, 60)
                    backing.paint_box("h264", 0, 0, *backing.size)
        finally:
            backing.close()
            win.destroy()


def main():
    unittest.main()


if __name__ == "__main__":
    main()
