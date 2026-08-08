#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest
from unittest.mock import patch

from OpenGL.GL import GL_RGB8, GL_RGBA8

from xpra.client.gl import gl_window_backing_base as glb
from xpra.util import typedict


def noop(*_args, **_kwargs):
    pass


class _TestBacking(glb.GLWindowBackingBase):

    def __init__(self):
        self.internal_format = GL_RGBA8
        self.textures = [0] * (glb.TEX_RGB + 1)
        self.draw_needs_refresh = True

    def gravity_adjust(self, x, y, _options):
        return x, y

    def pixels_for_upload(self, img_data):
        return "test", img_data

    def gl_init(self, skip_fbo=False) -> None:
        pass

    def gl_marker(self, *_args) -> None:
        pass

    def set_alignment(self, _width, _rowstride, _pixel_format) -> None:
        pass

    def paint_box(self, _encoding, _x, _y, _width, _height) -> None:
        pass


class TestPackedRgbUpload(unittest.TestCase):

    def test_padding_formats_use_rgb_texture(self):
        uploads = []

        def record_upload(*args):
            uploads.append(args)

        gl_functions = {
            "glEnable": noop,
            "glBindTexture": noop,
            "glTexParameteri": noop,
            "glTexImage2D": record_upload,
            "glBegin": noop,
            "glTexCoord2i": noop,
            "glVertex2i": noop,
            "glEnd": noop,
            "glDisable": noop,
        }
        backing = _TestBacking()
        with patch.multiple(glb, **gl_functions):
            for rgb_format, expected_internal_format in (
                ("BGRX", GL_RGB8),
                ("RGBX", GL_RGB8),
                ("BGRA", GL_RGBA8),
                ("RGBA", GL_RGBA8),
            ):
                uploads.clear()
                pixels = b"\0" * 8
                backing.gl_paint_rgb(object(), rgb_format, pixels,
                                     0, 0, 2, 1, 2, 1, 8, typedict(), [])
                assert uploads, f"{rgb_format} pixel data was not uploaded"
                internal_format = uploads[0][2]
                assert internal_format == expected_internal_format, \
                    f"{rgb_format}: expected {expected_internal_format}, got {internal_format}"


if __name__ == "__main__":
    unittest.main()
