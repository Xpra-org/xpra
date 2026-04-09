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


def main():
    unittest.main()


if __name__ == "__main__":
    main()
