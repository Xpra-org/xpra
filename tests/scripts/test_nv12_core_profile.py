#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Netflix, Inc.
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.
# ABOUTME: Validates the NV12 shader with GL_R8/GL_RG8 on core and compat profiles.
# ABOUTME: Regression test for #4829 (GL_LUMINANCE removed from core GL 3.3+).

"""
Headless EGL test for NV12 shader on core-profile-compatible GL formats.

GL_LUMINANCE / GL_LUMINANCE_ALPHA are removed from core GL 3.3+.
The fix uses GL_R8/GL_RG8 (internal) + GL_RED/GL_RG (data) instead.

On GL_RG, the two bytes map to:
  .r = byte 0 (U)
  .g = byte 1 (V)
  .b = 0.0
  .a = 1.0

So the shader must read V via `.g` (not `.a`).

Usage:
  PYTHONPATH=. python3 tests/scripts/test_nv12_core_profile.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from gl_helpers import create_egl_context, compile_shader, link_program, render_nv12


def test_nv12_core_formats():
    """Test NV12 shader with GL_R8/GL_RG8 formats (core profile compatible)."""
    from OpenGL.GL import (
        GL_FRAGMENT_SHADER, GL_VERTEX_SHADER,
        GL_R8, GL_RG8, GL_RED, GL_RG,
        glGetString, GL_RENDERER, GL_VERSION,
    )

    renderer = glGetString(GL_RENDERER)
    version = glGetString(GL_VERSION)
    print(f"GL renderer: {renderer.decode() if renderer else 'unknown'}")
    print(f"GL version:  {version.decode() if version else 'unknown'}")

    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
    from xpra.opengl.shaders import gen_NV12_to_RGB, VERTEX_SHADER

    vertex = compile_shader(VERTEX_SHADER, GL_VERTEX_SHADER)
    nv12_source = gen_NV12_to_RGB(cs="bt601", full_range=True)
    fragment = compile_shader(nv12_source, GL_FRAGMENT_SHADER)
    program = link_program(vertex, fragment)

    # 8x8 Y (mid-gray 0x80), 4x4 UV (U=0x80 neutral, V=0x40 green-shifted)
    y_w, y_h = 8, 8
    uv_w, uv_h = 4, 4
    y_data = bytes([0x80] * (y_w * y_h))
    uv_data = bytes([0x80, 0x40] * (uv_w * uv_h))

    pixels = render_nv12(
        program, y_data, uv_data, y_w, y_h, uv_w, uv_h, y_w, y_h,
        y_internal=GL_R8, y_data_fmt=GL_RED,
        uv_internal=GL_RG8, uv_data_fmt=GL_RG,
    )

    # Read center pixel (4,4)
    offset = (4 * y_w + 4) * 4
    r, g, b, a = pixels[offset], pixels[offset+1], pixels[offset+2], pixels[offset+3]
    print(f"\nTest — NV12 with GL_R8/GL_RG8 formats, V=0x40:")
    print(f"  Center pixel: R={r} G={g} B={b} A={a}")

    # With correct V channel read (V=0x40): BT.601 full-range -> R~39
    # With broken .a read on GL_RG: .a=1.0, v=0.5 -> R~228 (very red)
    assert r < 100, (
        f"FAIL: R={r}, expected <100. "
        f"V channel not read correctly — likely reading .a (=1.0) instead of .g on GL_RG"
    )
    print(f"  PASS: R={r} < 100 — V channel read correctly via GL_RG")


def main():
    # Test on core profile (where GL_LUMINANCE is invalid)
    print("=" * 60)
    print("Testing NV12 shader with GL_R8/GL_RG8 on CORE profile")
    print("=" * 60)
    create_egl_context(core=True)
    test_nv12_core_formats()

    # Also test on compat profile (ensure GL_RG still works there)
    print()
    print("=" * 60)
    print("Testing NV12 shader with GL_R8/GL_RG8 on COMPAT profile")
    print("=" * 60)
    create_egl_context(core=False)
    test_nv12_core_formats()

    print(f"\nAll core profile NV12 tests passed!")


if __name__ == "__main__":
    main()
