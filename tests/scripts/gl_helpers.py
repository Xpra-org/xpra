#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Netflix, Inc.
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.
# ABOUTME: Shared GL test utilities for headless EGL context creation,
# ABOUTME: shader compilation, and NV12 texture rendering with readback.

import os

os.environ["PYOPENGL_PLATFORM"] = "egl"


def create_egl_context(core=True):
    """Headless GL 3.3 context via EGL device platform.

    core=True requests a core profile (GL_LUMINANCE invalid).
    core=False requests a compat profile (GL_LUMINANCE works).
    """
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
    EGL_CONTEXT_OPENGL_COMPATIBILITY_PROFILE_BIT = 0x00000002
    profile_bit = EGL_CONTEXT_OPENGL_CORE_PROFILE_BIT if core else EGL_CONTEXT_OPENGL_COMPATIBILITY_PROFILE_BIT
    ctx_attribs = (c_int * 7)(
        EGL_CONTEXT_MAJOR_VERSION, 3, EGL_CONTEXT_MINOR_VERSION, 3,
        EGL_CONTEXT_OPENGL_PROFILE_MASK, profile_bit,
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
                y_internal=None, y_data_fmt=None, uv_internal=None, uv_data_fmt=None,
                uniform_y_name="Y", uniform_uv_name="UV"):
    """Upload NV12 textures, render with the given shader, read back pixels.

    GL format parameters default to GL_R8/GL_RG8 (core-profile-compatible).
    """
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
        glGenFramebuffers, glClear, glClearColor,
        GL_COLOR_BUFFER_BIT, GL_COLOR_ATTACHMENT0,
        GL_FLOAT, GL_ARRAY_BUFFER, GL_STATIC_DRAW, GL_FALSE as GL_F,
        GL_TRIANGLE_STRIP,
        glGenVertexArrays, glBindVertexArray,
        glGenBuffers, glBindBuffer, glBufferData,
        glVertexAttribPointer, glEnableVertexAttribArray, glDisableVertexAttribArray,
        glDrawArrays, glDrawBuffer, glReadBuffer, glReadPixels,
    )
    from OpenGL.GL.ARB.framebuffer_object import (
        GL_FRAMEBUFFER, GL_READ_FRAMEBUFFER,
        glBindFramebuffer as bindFBO, glFramebufferTexture2D as fboTex2D,
    )

    if y_internal is None:
        y_internal = GL_R8
    if y_data_fmt is None:
        y_data_fmt = GL_RED
    if uv_internal is None:
        uv_internal = GL_RG8
    if uv_data_fmt is None:
        uv_data_fmt = GL_RG

    target = GL_TEXTURE_RECTANGLE
    tex_y, tex_uv, tex_fbo = glGenTextures(3)

    # Upload Y plane
    glActiveTexture(GL_TEXTURE0)
    glBindTexture(target, tex_y)
    glTexParameteri(target, GL_TEXTURE_MAG_FILTER, GL_NEAREST)
    glTexParameteri(target, GL_TEXTURE_MIN_FILTER, GL_NEAREST)
    glPixelStorei(GL_UNPACK_ROW_LENGTH, 0)
    glPixelStorei(GL_UNPACK_ALIGNMENT, 1)
    glTexImage2D(target, 0, y_internal, y_w, y_h, 0, y_data_fmt, GL_UNSIGNED_BYTE, y_data)

    # Upload UV plane
    glActiveTexture(GL_TEXTURE1)
    glBindTexture(target, tex_uv)
    glTexParameteri(target, GL_TEXTURE_MAG_FILTER, GL_NEAREST)
    glTexParameteri(target, GL_TEXTURE_MIN_FILTER, GL_NEAREST)
    glTexImage2D(target, 0, uv_internal, uv_w, uv_h, 0,
                 uv_data_fmt, GL_UNSIGNED_BYTE, uv_data)

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
    glUniform1i(glGetUniformLocation(program, uniform_y_name), 0)

    glActiveTexture(GL_TEXTURE1)
    glBindTexture(target, tex_uv)
    glUniform1i(glGetUniformLocation(program, uniform_uv_name), 1)

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
