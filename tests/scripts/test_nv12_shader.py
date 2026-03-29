#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Netflix, Inc.
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.
# ABOUTME: Validates the NV12 OpenGL shader against known test patterns.
# ABOUTME: Exercises four NV12 bugs: .g swizzle, uniform binding, UV coords, texture allocation.

"""
Headless EGL test for the NV12 shader using GL_R8/GL_RG8 (core-profile-compatible).

Tests:
  1. .g swizzle — V channel read via GL_RG .g component
  2. Uniform binding — "Y" and "UV" uniforms correctly bound to texture units
  3. UV coordinate scaling — UV texture at half resolution, shader reads at pos*0.5
  4. Texture allocation — UV texture width must match upload width for GL_RG

Usage:
  PYTHONPATH=. python3 tests/scripts/test_nv12_shader.py
"""

import os
import sys

os.environ["PYOPENGL_PLATFORM"] = "egl"


def create_egl_context():
    """Headless GL 3.3 core profile context via EGL device platform."""
    import ctypes
    from ctypes import pointer, c_int, c_void_p, POINTER, CFUNCTYPE
    from OpenGL.EGL import (
        eglGetProcAddress, eglInitialize, eglChooseConfig,
        eglCreatePbufferSurface, eglBindAPI, eglCreateContext, eglMakeCurrent,
        EGL_SURFACE_TYPE, EGL_PBUFFER_BIT, EGL_RED_SIZE, EGL_GREEN_SIZE,
        EGL_BLUE_SIZE, EGL_ALPHA_SIZE, EGL_RENDERABLE_TYPE, EGL_OPENGL_BIT,
        EGL_NONE, EGL_WIDTH, EGL_HEIGHT, EGL_NO_CONTEXT,
        EGL_CONTEXT_MAJOR_VERSION, EGL_CONTEXT_MINOR_VERSION,
        EGL_OPENGL_API, EGLConfig,
    )
    QUERY_DEVICES_T = CFUNCTYPE(ctypes.c_bool, ctypes.c_int, POINTER(c_void_p), POINTER(c_int))
    GET_PLATFORM_DISPLAY_T = CFUNCTYPE(c_void_p, c_void_p, c_void_p, POINTER(c_int))
    query_ptr = eglGetProcAddress(b"eglQueryDevicesEXT")
    platform_ptr = eglGetProcAddress(b"eglGetPlatformDisplayEXT")
    if not query_ptr or not platform_ptr:
        raise RuntimeError("EGL device platform extensions not available")
    eglQueryDevicesEXT = QUERY_DEVICES_T(query_ptr)
    eglGetPlatformDisplayEXT = GET_PLATFORM_DISPLAY_T(platform_ptr)
    devices = (c_void_p * 4)()
    num_devices = c_int()
    eglQueryDevicesEXT(4, devices, pointer(num_devices))
    if num_devices.value == 0:
        raise RuntimeError("No EGL devices found")
    EGL_PLATFORM_DEVICE_EXT = 0x313F
    display = eglGetPlatformDisplayEXT(EGL_PLATFORM_DEVICE_EXT, devices[0], None)
    major, minor = c_int(), c_int()
    eglInitialize(display, pointer(major), pointer(minor))
    config_attribs = (c_int * 13)(
        EGL_SURFACE_TYPE, EGL_PBUFFER_BIT,
        EGL_RED_SIZE, 8, EGL_GREEN_SIZE, 8, EGL_BLUE_SIZE, 8, EGL_ALPHA_SIZE, 8,
        EGL_RENDERABLE_TYPE, EGL_OPENGL_BIT,
        EGL_NONE,
    )
    configs = (EGLConfig * 1)()
    num = c_int()
    eglChooseConfig(display, config_attribs, configs, 1, pointer(num))
    if num.value == 0:
        raise RuntimeError("No suitable EGL config found")
    surface_attribs = (c_int * 5)(EGL_WIDTH, 1, EGL_HEIGHT, 1, EGL_NONE)
    surface = eglCreatePbufferSurface(display, configs[0], surface_attribs)
    eglBindAPI(EGL_OPENGL_API)
    EGL_CONTEXT_OPENGL_PROFILE_MASK = 0x30FD
    EGL_CONTEXT_OPENGL_CORE_PROFILE_BIT = 0x00000001
    ctx_attribs = (c_int * 7)(
        EGL_CONTEXT_MAJOR_VERSION, 3, EGL_CONTEXT_MINOR_VERSION, 3,
        EGL_CONTEXT_OPENGL_PROFILE_MASK, EGL_CONTEXT_OPENGL_CORE_PROFILE_BIT,
        EGL_NONE,
    )
    context = eglCreateContext(display, configs[0], EGL_NO_CONTEXT, ctx_attribs)
    eglMakeCurrent(display, surface, surface, context)


def compile_shader(source, shader_type):
    from OpenGL.GL import (
        glCreateShader, glShaderSource, glCompileShader,
        glGetShaderiv, glGetShaderInfoLog, GL_COMPILE_STATUS, GL_FALSE,
    )
    shader = glCreateShader(shader_type)
    glShaderSource(shader, source)
    glCompileShader(shader)
    if glGetShaderiv(shader, GL_COMPILE_STATUS) == GL_FALSE:
        info = glGetShaderInfoLog(shader)
        raise RuntimeError(f"Shader compile error: {info}")
    return shader


def link_program(vertex, fragment):
    from OpenGL.GL import (
        glCreateProgram, glAttachShader, glLinkProgram,
        glGetProgramiv, glGetProgramInfoLog, GL_LINK_STATUS, GL_FALSE,
    )
    program = glCreateProgram()
    glAttachShader(program, vertex)
    glAttachShader(program, fragment)
    glLinkProgram(program)
    if glGetProgramiv(program, GL_LINK_STATUS) == GL_FALSE:
        info = glGetProgramInfoLog(program)
        raise RuntimeError(f"Program link error: {info}")
    return program


def render_nv12(program, y_data, uv_data, y_w, y_h, uv_w, uv_h, out_w, out_h,
                uniform_y_name="Y", uniform_uv_name="UV"):
    """Upload NV12 textures using GL_R8/GL_RG8, render with shader, read back pixels."""
    from ctypes import c_float, c_void_p
    from OpenGL.GL import (
        glGenTextures, glBindTexture, glTexImage2D, glTexParameteri,
        glActiveTexture, glPixelStorei,
        GL_TEXTURE_RECTANGLE, GL_TEXTURE0, GL_TEXTURE1,
        GL_TEXTURE_MAG_FILTER, GL_TEXTURE_MIN_FILTER, GL_NEAREST,
        GL_UNPACK_ROW_LENGTH, GL_UNPACK_ALIGNMENT,
        GL_R8, GL_RG8, GL_RED, GL_RG, GL_UNSIGNED_BYTE,
        GL_RGBA, GL_RGBA8,
        glViewport, glUseProgram, glGetUniformLocation, glUniform1i, glUniform2f,
        glGenFramebuffers,
        glDrawBuffer, glReadBuffer, glReadPixels, glClear, glClearColor,
        GL_COLOR_BUFFER_BIT, GL_COLOR_ATTACHMENT0,
        GL_FLOAT, GL_ARRAY_BUFFER, GL_STATIC_DRAW, GL_FALSE as GL_F,
        GL_TRIANGLE_STRIP,
        glGenVertexArrays, glBindVertexArray,
        glGenBuffers, glBindBuffer, glBufferData,
        glVertexAttribPointer, glEnableVertexAttribArray, glDisableVertexAttribArray,
        glDrawArrays,
    )
    from OpenGL.GL.ARB.framebuffer_object import (
        GL_FRAMEBUFFER, GL_READ_FRAMEBUFFER,
        glBindFramebuffer as bindFBO, glFramebufferTexture2D as fboTex2D,
    )

    target = GL_TEXTURE_RECTANGLE
    tex_y, tex_uv, tex_fbo = glGenTextures(3)

    # Upload Y plane (single channel, GL_R8)
    glActiveTexture(GL_TEXTURE0)
    glBindTexture(target, tex_y)
    glTexParameteri(target, GL_TEXTURE_MAG_FILTER, GL_NEAREST)
    glTexParameteri(target, GL_TEXTURE_MIN_FILTER, GL_NEAREST)
    glPixelStorei(GL_UNPACK_ROW_LENGTH, 0)
    glPixelStorei(GL_UNPACK_ALIGNMENT, 1)
    glTexImage2D(target, 0, GL_R8, y_w, y_h, 0, GL_RED, GL_UNSIGNED_BYTE, y_data)

    # Upload UV plane (two channels interleaved, GL_RG8)
    glActiveTexture(GL_TEXTURE1)
    glBindTexture(target, tex_uv)
    glTexParameteri(target, GL_TEXTURE_MAG_FILTER, GL_NEAREST)
    glTexParameteri(target, GL_TEXTURE_MIN_FILTER, GL_NEAREST)
    glTexImage2D(target, 0, GL_RG8, uv_w, uv_h, 0,
                 GL_RG, GL_UNSIGNED_BYTE, uv_data)

    # FBO for readback
    fbo = glGenFramebuffers(1)
    bindFBO(GL_FRAMEBUFFER, fbo)
    glBindTexture(target, tex_fbo)
    glTexParameteri(target, GL_TEXTURE_MAG_FILTER, GL_NEAREST)
    glTexParameteri(target, GL_TEXTURE_MIN_FILTER, GL_NEAREST)
    glTexImage2D(target, 0, GL_RGBA8, out_w, out_h, 0, GL_RGBA, GL_UNSIGNED_BYTE, None)
    fboTex2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, target, tex_fbo, 0)
    glDrawBuffer(GL_COLOR_ATTACHMENT0)
    glViewport(0, 0, out_w, out_h)
    glClearColor(0, 0, 0, 1)
    glClear(GL_COLOR_BUFFER_BIT)

    # Bind shader and uniforms
    glUseProgram(program)

    glActiveTexture(GL_TEXTURE0)
    glBindTexture(target, tex_y)
    loc_y = glGetUniformLocation(program, uniform_y_name)
    glUniform1i(loc_y, 0)

    glActiveTexture(GL_TEXTURE1)
    glBindTexture(target, tex_uv)
    loc_uv = glGetUniformLocation(program, uniform_uv_name)
    glUniform1i(loc_uv, 1)

    glUniform2f(glGetUniformLocation(program, "viewport_pos"), 0, 0)
    glUniform2f(glGetUniformLocation(program, "scaling"), 1.0, 1.0)

    # Fullscreen quad
    vao = glGenVertexArrays(1)
    glBindVertexArray(vao)
    vbo = glGenBuffers(1)
    vertices = [-1, -1, 1, -1, -1, 1, 1, 1]
    c_verts = (c_float * 8)(*vertices)
    glBindBuffer(GL_ARRAY_BUFFER, vbo)
    glBufferData(GL_ARRAY_BUFFER, 32, c_verts, GL_STATIC_DRAW)
    glVertexAttribPointer(0, 2, GL_FLOAT, GL_F, 0, c_void_p(0))
    glEnableVertexAttribArray(0)
    glDrawArrays(GL_TRIANGLE_STRIP, 0, 4)
    glDisableVertexAttribArray(0)
    glBindVertexArray(0)
    glUseProgram(0)

    # Read back
    bindFBO(GL_READ_FRAMEBUFFER, fbo)
    glReadBuffer(GL_COLOR_ATTACHMENT0)
    pixels = glReadPixels(0, 0, out_w, out_h, GL_RGBA, GL_UNSIGNED_BYTE)
    return bytes(pixels)


def main():
    create_egl_context()

    from OpenGL.GL import GL_FRAGMENT_SHADER, GL_VERTEX_SHADER, glGetString, GL_RENDERER
    renderer = glGetString(GL_RENDERER)
    print(f"GL renderer: {renderer.decode() if renderer else 'unknown'}")

    # Import the shader generator
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
    from xpra.opengl.shaders import gen_NV12_to_RGB, VERTEX_SHADER

    vertex = compile_shader(VERTEX_SHADER, GL_VERTEX_SHADER)

    # Compile the NV12 shader
    nv12_source = gen_NV12_to_RGB(cs="bt601", full_range=True)
    fragment = compile_shader(nv12_source, GL_FRAGMENT_SHADER)
    program = link_program(vertex, fragment)

    # ── Test 1: Basic NV12 with correct uniform binding ──
    # 8×8 Y (mid-gray 0x80), 4×4 UV (U=0x80 neutral, V=0x40 green-shifted)
    y_w, y_h = 8, 8
    uv_w, uv_h = 4, 4
    y_data = bytes([0x80] * (y_w * y_h))
    uv_data = bytes([0x80, 0x40] * (uv_w * uv_h))

    pixels = render_nv12(program, y_data, uv_data, y_w, y_h, uv_w, uv_h, y_w, y_h,
                         uniform_y_name="Y", uniform_uv_name="UV")
    # Read center pixel (4,4)
    offset = (4 * y_w + 4) * 4
    r, g, b, a = pixels[offset], pixels[offset+1], pixels[offset+2], pixels[offset+3]
    print(f"\nTest 1 — Correct uniforms (Y, UV), V=0x40:")
    print(f"  Center pixel: R={r} G={g} B={b} A={a}")
    # With .g swizzle on GL_RG and V=0x40: BT.601 full-range → R≈39
    assert r < 100, f"FAIL: R={r}, expected <100 (V channel not read correctly via .g)"
    print(f"  PASS: R={r} < 100 — .g swizzle works")

    # ── Test 2: Simulate broken uniform binding ──
    # Recompile a fresh program so no uniform state carries over from test 1.
    # Bind with wrong names ("N", "V") — neither matches the shader's "Y"/"UV" uniforms.
    # Both glGetUniformLocation calls return -1, so both samplers keep default unit 0 (Y).
    fragment2 = compile_shader(nv12_source, GL_FRAGMENT_SHADER)
    program2 = link_program(vertex, fragment2)
    pixels_bad = render_nv12(program2, y_data, uv_data, y_w, y_h, uv_w, uv_h, y_w, y_h,
                             uniform_y_name="N", uniform_uv_name="V")
    offset = (4 * y_w + 4) * 4
    r2, g2, b2, a2 = pixels_bad[offset], pixels_bad[offset+1], pixels_bad[offset+2], pixels_bad[offset+3]
    print(f"\nTest 2 — Old render_planar_update uniform names (N, V):")
    print(f"  Center pixel: R={r2} G={g2} B={b2} A={a2}")
    # UV sampler reads GL_R8 Y texture: .r = 0.502, .g = 0.0 (GL_R8 has no green)
    # u = 0.502 - 0.5 = 0.002 (near zero), v = 0.0 - 0.5 = -0.5
    # R = Y + 1.402*(-0.5) ≈ 0.502 - 0.701 ≈ 0 → clamped to 0
    assert r2 < 10, f"FAIL: R={r2}, expected <10 when UV reads Y data via GL_R8 (.g=0)"
    # The result should look very different from the correct Test 1 output
    assert abs(r2 - r) > 20, f"FAIL: broken uniforms gave same result as correct (R={r2} vs {r})"
    print(f"  PASS: R={r2} < 10 — wrong uniforms produce wrong colors")

    # ── Test 3: UV coordinate scaling — large texture ──
    # 16×16 Y, 8×8 UV. Left half UV=green-shifted, right half UV=red-shifted.
    y_w2, y_h2 = 16, 16
    uv_w2, uv_h2 = 8, 8
    y_data2 = bytes([0x80] * (y_w2 * y_h2))
    # UV plane: left 4 cols = (U=0x80, V=0x40) green, right 4 cols = (U=0x80, V=0xC0) red
    uv_rows = []
    for row in range(uv_h2):
        for col in range(uv_w2):
            if col < 4:
                uv_rows.extend([0x80, 0x40])  # neutral U, low V → greenish
            else:
                uv_rows.extend([0x80, 0xC0])  # neutral U, high V → reddish
    uv_data2 = bytes(uv_rows)

    pixels3 = render_nv12(program, y_data2, uv_data2, y_w2, y_h2, uv_w2, uv_h2, y_w2, y_h2)

    # Sample left quarter (x=2) and right quarter (x=14) at middle height
    left_offset = (8 * y_w2 + 2) * 4
    right_offset = (8 * y_w2 + 14) * 4
    r_left = pixels3[left_offset]
    r_right = pixels3[right_offset]
    print(f"\nTest 3 — UV coordinate scaling (16×16 Y, 8×8 UV with spatial variation):")
    print(f"  Left pixel (x=2):  R={r_left}")
    print(f"  Right pixel (x=14): R={r_right}")
    # With correct pos*0.5: left reads low-V (R≈39), right reads high-V (R≈219)
    # Without pos*0.5: coordinates > 8 clamp to edge, right side reads edge UV
    assert r_right > r_left + 50, \
        f"FAIL: Right R ({r_right}) not significantly > left R ({r_left}) — UV coords not scaled"
    print(f"  PASS: Right R ({r_right}) >> left R ({r_left}) — UV coordinate scaling works")

    # ── Test 4: UV texture allocation must match upload width ──
    # Allocate UV texture wider than the upload (simulating the old bug where
    # glTexImage2D used width//div_w but glTexSubImage2D used width//div_w//2).
    from ctypes import c_float, c_void_p
    from OpenGL.GL import (
        glGenTextures, glTexSubImage2D,
        glGenFramebuffers, glGenVertexArrays, glGenBuffers,
        glBindBuffer, glBufferData, glVertexAttribPointer, glEnableVertexAttribArray,
        glDeleteBuffers, glDisableVertexAttribArray, glBindVertexArray,
        GL_ARRAY_BUFFER, GL_STATIC_DRAW, GL_FLOAT, GL_FALSE as GL_F,
        GL_R8, GL_RG8, GL_RED, GL_RG,
        GL_RGBA8, GL_RGBA, GL_UNSIGNED_BYTE,
        GL_TEXTURE_RECTANGLE, GL_TEXTURE0, GL_TEXTURE1,
        GL_TEXTURE_MAG_FILTER, GL_TEXTURE_MIN_FILTER, GL_NEAREST, GL_LINEAR,
        GL_TRIANGLE_STRIP, GL_COLOR_ATTACHMENT0,
        glActiveTexture, glBindTexture, glTexParameteri, glPixelStorei,
        glTexImage2D, glViewport, glUseProgram, glGetUniformLocation,
        glUniform1i, glUniform2f, glDrawArrays, glDrawBuffer, glReadBuffer,
        glReadPixels, GL_UNPACK_ROW_LENGTH, GL_UNPACK_ALIGNMENT,
    )
    from OpenGL.GL.ARB.framebuffer_object import (
        GL_FRAMEBUFFER, GL_READ_FRAMEBUFFER,
        glBindFramebuffer, glFramebufferTexture2D,
    )

    y_w4, y_h4 = 20, 8
    uv_w4, uv_h4 = 10, 4  # correct UV dimensions (half Y)
    y_data4 = bytes([0x80] * (y_w4 * y_h4))
    # All UV texels: U=0x80 (neutral), V=0x40 (greenish) — known good color
    uv_data4 = bytes([0x80, 0x40] * (uv_w4 * uv_h4))

    # Allocate UV texture at DOUBLE the correct width (simulating the old bug)
    tex_y4, tex_uv_bad, tex_fbo4 = glGenTextures(3)
    target = GL_TEXTURE_RECTANGLE

    # Y texture — normal
    glActiveTexture(GL_TEXTURE0)
    glBindTexture(target, tex_y4)
    glTexParameteri(target, GL_TEXTURE_MAG_FILTER, GL_LINEAR)
    glTexParameteri(target, GL_TEXTURE_MIN_FILTER, GL_NEAREST)
    glPixelStorei(GL_UNPACK_ROW_LENGTH, 0)
    glPixelStorei(GL_UNPACK_ALIGNMENT, 1)
    glTexImage2D(target, 0, GL_R8, y_w4, y_h4, 0, GL_RED, GL_UNSIGNED_BYTE, y_data4)

    # UV texture — allocated too wide (bug: 2*uv_w4 instead of uv_w4)
    glActiveTexture(GL_TEXTURE1)
    glBindTexture(target, tex_uv_bad)
    glTexParameteri(target, GL_TEXTURE_MAG_FILTER, GL_LINEAR)
    glTexParameteri(target, GL_TEXTURE_MIN_FILTER, GL_NEAREST)
    # Allocate at double width — right half is uninitialized
    glTexImage2D(target, 0, GL_RG8, uv_w4 * 2, uv_h4, 0,
                 GL_RG, GL_UNSIGNED_BYTE, None)
    # Upload only the correct width
    glTexSubImage2D(target, 0, 0, 0, uv_w4, uv_h4,
                    GL_RG, GL_UNSIGNED_BYTE, uv_data4)

    # Render to FBO
    fbo4 = glGenFramebuffers(1)
    glBindFramebuffer(GL_FRAMEBUFFER, fbo4)
    glBindTexture(target, tex_fbo4)
    glTexParameteri(target, GL_TEXTURE_MAG_FILTER, GL_NEAREST)
    glTexParameteri(target, GL_TEXTURE_MIN_FILTER, GL_NEAREST)
    glTexImage2D(target, 0, GL_RGBA8, y_w4, y_h4, 0, GL_RGBA, GL_UNSIGNED_BYTE, None)
    glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, target, tex_fbo4, 0)
    glDrawBuffer(GL_COLOR_ATTACHMENT0)
    glViewport(0, 0, y_w4, y_h4)

    # Use the CORRECT program with proper uniforms
    fragment4 = compile_shader(nv12_source, GL_FRAGMENT_SHADER)
    program4 = link_program(vertex, fragment4)
    glUseProgram(program4)
    glActiveTexture(GL_TEXTURE0)
    glBindTexture(target, tex_y4)
    glUniform1i(glGetUniformLocation(program4, "Y"), 0)
    glActiveTexture(GL_TEXTURE1)
    glBindTexture(target, tex_uv_bad)
    glUniform1i(glGetUniformLocation(program4, "UV"), 1)
    glUniform2f(glGetUniformLocation(program4, "viewport_pos"), 0, 0)
    glUniform2f(glGetUniformLocation(program4, "scaling"), 1.0, 1.0)

    vao4 = glGenVertexArrays(1)
    glBindVertexArray(vao4)
    vbo4 = glGenBuffers(1)
    c_verts4 = (c_float * 8)(-1, -1, 1, -1, -1, 1, 1, 1)
    glBindBuffer(GL_ARRAY_BUFFER, vbo4)
    glBufferData(GL_ARRAY_BUFFER, 32, c_verts4, GL_STATIC_DRAW)
    glVertexAttribPointer(0, 2, GL_FLOAT, GL_F, 0, c_void_p(0))
    glEnableVertexAttribArray(0)
    glDrawArrays(GL_TRIANGLE_STRIP, 0, 4)
    glDeleteBuffers(1, [vbo4])
    glDisableVertexAttribArray(0)
    glBindVertexArray(0)
    glUseProgram(0)

    glBindFramebuffer(GL_READ_FRAMEBUFFER, fbo4)
    glReadBuffer(GL_COLOR_ATTACHMENT0)
    pixels4 = glReadPixels(0, 0, y_w4, y_h4, GL_RGBA, GL_UNSIGNED_BYTE)

    # Right edge pixel (x=19) — shader reads UV at 19*0.5=9.5, but UV texture is
    # 20 wide with only 10 columns of valid data. Column 10+ is uninitialized.
    right_edge = (4 * y_w4 + 19) * 4
    r4_right = pixels4[right_edge]
    # Center pixel (x=5) — well within the valid UV region
    center = (4 * y_w4 + 5) * 4
    r4_center = pixels4[center]
    print(f"\nTest 4 — UV texture allocation wider than upload (simulating old bug):")
    print(f"  Center pixel (x=5):     R={r4_center}")
    print(f"  Right edge pixel (x=19): R={r4_right}")
    # If the texture is correctly sized, both pixels read valid UV data and match.
    # With the over-wide allocation, the right edge reads uninitialized data.
    if abs(r4_right - r4_center) > 20:
        print(f"  DETECTED: over-wide UV allocation causes wrong colors at right edge")
        print(f"  (difference={abs(r4_right - r4_center)}, threshold=20)")
    else:
        print(f"  PASS: colors match (difference={abs(r4_right - r4_center)})")

    # Now test with CORRECT allocation (uv_w4, not uv_w4*2)
    pixels4b = render_nv12(program, y_data4, uv_data4, y_w4, y_h4, uv_w4, uv_h4, y_w4, y_h4)
    right_edge_b = (4 * y_w4 + 19) * 4
    r4b_right = pixels4b[right_edge_b]
    center_b = (4 * y_w4 + 5) * 4
    r4b_center = pixels4b[center_b]
    print(f"  Correct allocation — center R={r4b_center}, right edge R={r4b_right}")
    assert abs(r4b_right - r4b_center) <= 20, \
        f"FAIL: correct allocation still has edge mismatch ({r4b_right} vs {r4b_center})"
    print(f"  PASS: correct allocation gives consistent colors across the full width")

    print(f"\nAll NV12 shader tests passed!")


if __name__ == "__main__":
    main()
