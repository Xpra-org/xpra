#!/usr/bin/env python3
# ABOUTME: Benchmarks scaling quality and throughput for Cairo and OpenGL renderers.
# ABOUTME: Compares bilinear vs Catmull-Rom across multiple window sizes.

"""
Benchmark scaling quality and throughput for Cairo (bilinear/Catmull-Rom)
and OpenGL (bilinear blit/Catmull-Rom shader).

Usage:
    python3 tests/scripts/benchmark_scaling.py [--sizes 640x480,1920x1080] [--frames 100] [--scale 1.6]

Detects available backends automatically:
  - Cairo: requires pycairo
  - OpenGL: requires PyOpenGL + GPU (EGL device platform on Linux, WGL on Windows)
  - CPU reference: pure Python Catmull-Rom (always available)
"""

import argparse
import math
import os
import sys
import time

# Ensure the source tree's xpra package is importable when running as a script
# (not needed in frozen cx_Freeze builds where modules are bundled)
if not getattr(sys, "frozen", False):
    _repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    if _repo_root not in sys.path:
        sys.path.insert(0, _repo_root)


def catmull_rom_weights(t):
    """Compute the 4 Catmull-Rom weights for fractional position t in [0,1)."""
    w0 = t * (-0.5 + t * (1.0 - 0.5 * t))
    w1 = 1.0 + t * t * (-2.5 + 1.5 * t)
    w2 = t * (0.5 + t * (2.0 - 1.5 * t))
    w3 = t * t * (-0.5 + 0.5 * t)
    return w0, w1, w2, w3


def catmull_rom_2d_cpu(src, src_w, src_h, dst_w, dst_h):
    """
    CPU reference: 9-tap Catmull-Rom 2D upscale.
    src is a flat list of floats (grayscale), row-major, src_w * src_h elements.
    Returns a flat list of dst_w * dst_h floats.
    """
    dst = [0.0] * (dst_w * dst_h)
    sx = src_w / dst_w
    sy = src_h / dst_h

    def clamp_get(r, c):
        r = max(0, min(src_h - 1, r))
        c = max(0, min(src_w - 1, c))
        return src[r * src_w + c]

    def bilinear_sample(x, y):
        ix = int(math.floor(x - 0.5))
        iy = int(math.floor(y - 0.5))
        fx = x - (ix + 0.5)
        fy = y - (iy + 0.5)
        v00 = clamp_get(iy, ix)
        v10 = clamp_get(iy, ix + 1)
        v01 = clamp_get(iy + 1, ix)
        v11 = clamp_get(iy + 1, ix + 1)
        top = v00 * (1 - fx) + v10 * fx
        bot = v01 * (1 - fx) + v11 * fx
        return top * (1 - fy) + bot * fy

    for dy in range(dst_h):
        for dx in range(dst_w):
            coord_x = (dx + 0.5) * sx
            coord_y = (dy + 0.5) * sy

            cx = math.floor(coord_x - 0.5) + 0.5
            cy = math.floor(coord_y - 0.5) + 0.5
            fx = coord_x - cx
            fy = coord_y - cy

            wx = catmull_rom_weights(fx)
            wy = catmull_rom_weights(fy)

            w12x = wx[1] + wx[2]
            w12y = wy[1] + wy[2]
            off12x = wx[2] / w12x if w12x else 0
            off12y = wy[2] / w12y if w12y else 0

            pxs = [cx - 1.0, cx + off12x, cx + 2.0]
            pys = [cy - 1.0, cy + off12y, cy + 2.0]
            wxs = [wx[0], w12x, wx[3]]
            wys = [wy[0], w12y, wy[3]]

            val = 0.0
            for j in range(3):
                for i in range(3):
                    val += bilinear_sample(pxs[i], pys[j]) * wxs[i] * wys[j]
            dst[dy * dst_w + dx] = val
    return dst


def make_test_pattern(w, h):
    """Generate a test pattern with sharp edges and gradients."""
    data = [0.0] * (w * h)
    for y in range(h):
        for x in range(w):
            block = 8
            checker = ((x // block) + (y // block)) % 2
            gradient = x / w
            data[y * w + x] = checker * 0.7 + gradient * 0.3
    return data


def downsample_box(src, src_w, src_h, dst_w, dst_h):
    """Box-filter downsample (area averaging). Simulates what the server sends."""
    dst = [0.0] * (dst_w * dst_h)
    sx = src_w / dst_w
    sy = src_h / dst_h
    for dy in range(dst_h):
        for dx in range(dst_w):
            # Average all source pixels that fall within this destination pixel
            x0 = int(dx * sx)
            x1 = min(int((dx + 1) * sx), src_w)
            y0 = int(dy * sy)
            y1 = min(int((dy + 1) * sy), src_h)
            total = 0.0
            count = 0
            for yy in range(y0, y1):
                for xx in range(x0, x1):
                    total += src[yy * src_w + xx]
                    count += 1
            dst[dy * dst_w + dx] = total / count if count else 0
    return dst


def psnr(ref, test, n):
    """Compute PSNR between two flat float arrays."""
    mse = sum((ref[i] - test[i]) ** 2 for i in range(n)) / n
    if mse < 1e-12:
        return float('inf')
    return 10 * math.log10(1.0 / mse)


def bench_cpu_catmull_rom(src, src_w, src_h, dst_w, dst_h, frames):
    """Benchmark CPU Catmull-Rom and return (ms_per_frame, result)."""
    result = catmull_rom_2d_cpu(src, src_w, src_h, dst_w, dst_h)
    start = time.monotonic()
    for _ in range(frames):
        result = catmull_rom_2d_cpu(src, src_w, src_h, dst_w, dst_h)
    elapsed = time.monotonic() - start
    return elapsed / frames * 1000, result


def bench_cairo(src_surface, dst_w, dst_h, scale_x, scale_y, filter_const, frames):
    """Benchmark Cairo scaling and return (ms_per_frame, surface)."""
    import cairo
    dst = cairo.ImageSurface(cairo.Format.ARGB32, dst_w, dst_h)
    gc = cairo.Context(dst)

    # Warm up
    gc.save()
    gc.scale(scale_x, scale_y)
    gc.set_source_surface(src_surface, 0, 0)
    gc.get_source().set_filter(filter_const)
    gc.paint()
    gc.restore()

    start = time.monotonic()
    for _ in range(frames):
        gc.save()
        gc.scale(scale_x, scale_y)
        gc.set_source_surface(src_surface, 0, 0)
        gc.get_source().set_filter(filter_const)
        gc.paint()
        gc.restore()
    dst.flush()
    elapsed = time.monotonic() - start
    return elapsed / frames * 1000, dst


def surface_to_grayscale(surface, w, h):
    """Extract grayscale values from a Cairo ARGB32 surface."""
    buf = surface.get_data()
    stride = surface.get_stride()
    result = [0.0] * (w * h)
    for y in range(h):
        for x in range(w):
            offset = y * stride + x * 4
            b, g, r = buf[offset], buf[offset + 1], buf[offset + 2]
            result[y * w + x] = (0.299 * r + 0.587 * g + 0.114 * b) / 255.0
    return result


def make_cairo_surface(pattern, w, h):
    """Create a Cairo ARGB32 surface from a grayscale float pattern."""
    import cairo
    surface = cairo.ImageSurface(cairo.Format.ARGB32, w, h)
    buf = surface.get_data()
    stride = surface.get_stride()
    for y in range(h):
        for x in range(w):
            v = int(max(0, min(1, pattern[y * w + x])) * 255)
            offset = y * stride + x * 4
            buf[offset] = v      # B
            buf[offset + 1] = v  # G
            buf[offset + 2] = v  # R
            buf[offset + 3] = 255  # A
    surface.mark_dirty()
    return surface


# --- OpenGL benchmark support ---

def create_gl_context():
    """
    Create a GL context for benchmarking.
    Tries platform-appropriate methods: EGL device (Linux headless), WGL (Windows).
    """
    if sys.platform == "win32":
        return _create_wgl_context()
    else:
        os.environ["PYOPENGL_PLATFORM"] = "egl"
        return _create_egl_context()


def _create_egl_context():
    """Headless GL 3.3 context via EGL device platform (NVIDIA Linux)."""
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
    GET_PLATFORM_DISPLAY_T = CFUNCTYPE(c_void_p, ctypes.c_uint, c_void_p, POINTER(c_int))

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
    ctx_attribs = (c_int * 5)(
        EGL_CONTEXT_MAJOR_VERSION, 3, EGL_CONTEXT_MINOR_VERSION, 3, EGL_NONE,
    )
    context = eglCreateContext(display, configs[0], EGL_NO_CONTEXT, ctx_attribs)
    eglMakeCurrent(display, surface, surface, context)


def _create_wgl_context():
    """GL context via WGL with a hidden window (Windows)."""
    import ctypes
    from ctypes import sizeof, byref, c_void_p

    user32 = ctypes.windll.user32
    gdi32 = ctypes.windll.gdi32
    opengl32 = ctypes.WinDLL("opengl32")

    # Register a minimal window class.
    # WPARAM is pointer-sized unsigned, LPARAM/LRESULT are pointer-sized signed.
    WNDPROC_T = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, ctypes.c_void_p,
                                    ctypes.c_uint, ctypes.c_size_t, ctypes.c_ssize_t)
    user32.DefWindowProcA.argtypes = [ctypes.c_void_p, ctypes.c_uint,
                                      ctypes.c_size_t, ctypes.c_ssize_t]
    user32.DefWindowProcA.restype = ctypes.c_ssize_t

    def wnd_proc(hwnd, msg, wparam, lparam):
        return user32.DefWindowProcA(hwnd, msg, wparam, lparam)

    # prevent garbage collection of the callback
    _wnd_proc_cb = WNDPROC_T(wnd_proc)

    class WNDCLASSEX(ctypes.Structure):
        _fields_ = [
            ("cbSize", ctypes.c_uint),
            ("style", ctypes.c_uint),
            ("lpfnWndProc", WNDPROC_T),
            ("cbClsExtra", ctypes.c_int),
            ("cbWndExtra", ctypes.c_int),
            ("hInstance", ctypes.c_void_p),
            ("hIcon", ctypes.c_void_p),
            ("hCursor", ctypes.c_void_p),
            ("hBrush", ctypes.c_void_p),
            ("lpszMenuName", ctypes.c_char_p),
            ("lpszClassName", ctypes.c_char_p),
            ("hIconSm", ctypes.c_void_p),
        ]

    h_inst = ctypes.windll.kernel32.GetModuleHandleA(None)
    classname = b"XpraBenchmarkGL"
    wc = WNDCLASSEX()
    wc.cbSize = sizeof(WNDCLASSEX)
    wc.style = 0x0020 | 0x0002 | 0x0001  # CS_OWNDC | CS_HREDRAW | CS_VREDRAW
    wc.lpfnWndProc = _wnd_proc_cb
    wc.hInstance = h_inst
    wc.hBrush = 5  # COLOR_WINDOW
    wc.lpszClassName = classname
    atom = user32.RegisterClassExA(byref(wc))
    if not atom:
        raise RuntimeError("RegisterClassExA failed")

    # Create hidden window
    hwnd = user32.CreateWindowExA(
        0, atom, b"Xpra Benchmark GL",
        0x00000000 | 0x00080000,  # WS_OVERLAPPED | WS_SYSMENU
        -2147483648, -2147483648, 1, 1,  # CW_USEDEFAULT
        None, None, h_inst, None,
    )
    if not hwnd:
        raise RuntimeError("CreateWindowExA failed")

    hdc = user32.GetDC(hwnd)

    # Set pixel format
    class PIXELFORMATDESCRIPTOR(ctypes.Structure):
        _fields_ = [
            ("nSize", ctypes.c_ushort), ("nVersion", ctypes.c_ushort),
            ("dwFlags", ctypes.c_uint), ("iPixelType", ctypes.c_ubyte),
            ("cColorBits", ctypes.c_ubyte),
            ("cRedBits", ctypes.c_ubyte), ("cRedShift", ctypes.c_ubyte),
            ("cGreenBits", ctypes.c_ubyte), ("cGreenShift", ctypes.c_ubyte),
            ("cBlueBits", ctypes.c_ubyte), ("cBlueShift", ctypes.c_ubyte),
            ("cAlphaBits", ctypes.c_ubyte), ("cAlphaShift", ctypes.c_ubyte),
            ("cAccumBits", ctypes.c_ubyte),
            ("cAccumRedBits", ctypes.c_ubyte), ("cAccumGreenBits", ctypes.c_ubyte),
            ("cAccumBlueBits", ctypes.c_ubyte), ("cAccumAlphaBits", ctypes.c_ubyte),
            ("cDepthBits", ctypes.c_ubyte), ("cStencilBits", ctypes.c_ubyte),
            ("cAuxBuffers", ctypes.c_ubyte), ("iLayerType", ctypes.c_ubyte),
            ("bReserved", ctypes.c_ubyte),
            ("dwLayerMask", ctypes.c_uint), ("dwVisibleMask", ctypes.c_uint),
            ("dwDamageMask", ctypes.c_uint),
        ]

    pfd = PIXELFORMATDESCRIPTOR()
    pfd.nSize = sizeof(PIXELFORMATDESCRIPTOR)
    pfd.nVersion = 1
    pfd.dwFlags = 0x04 | 0x20 | 0x01  # PFD_DRAW_TO_WINDOW | PFD_SUPPORT_OPENGL | PFD_DOUBLEBUFFER
    pfd.iPixelType = 0  # PFD_TYPE_RGBA
    pfd.cColorBits = 32
    pfd.cDepthBits = 24
    pfd.cStencilBits = 2

    pf = gdi32.ChoosePixelFormat(hdc, byref(pfd))
    if not pf:
        raise RuntimeError("ChoosePixelFormat failed")
    gdi32.SetPixelFormat(hdc, pf, byref(pfd))

    hglrc = opengl32.wglCreateContext(hdc)
    if not hglrc:
        raise RuntimeError("wglCreateContext failed")
    opengl32.wglMakeCurrent(hdc, hglrc)

    # Store refs to prevent GC (the context must stay alive for the benchmark)
    _create_wgl_context._refs = (_wnd_proc_cb, hwnd, hdc, hglrc)


def compile_shader(source, shader_type):
    """Compile a GLSL shader and return its handle."""
    from OpenGL.GL import (
        glCreateShader, glShaderSource, glCompileShader,
        glGetShaderiv, glGetShaderInfoLog, GL_COMPILE_STATUS,
    )
    shader = glCreateShader(shader_type)
    glShaderSource(shader, source)
    glCompileShader(shader)
    if not glGetShaderiv(shader, GL_COMPILE_STATUS):
        log = glGetShaderInfoLog(shader)
        raise RuntimeError(f"Shader compile failed: {log}")
    return shader


def link_program(vertex, fragment):
    """Link vertex + fragment shaders into a program."""
    from OpenGL.GL import (
        glCreateProgram, glAttachShader, glLinkProgram,
        glGetProgramiv, glGetProgramInfoLog, GL_LINK_STATUS,
    )
    program = glCreateProgram()
    glAttachShader(program, vertex)
    glAttachShader(program, fragment)
    glLinkProgram(program)
    if not glGetProgramiv(program, GL_LINK_STATUS):
        log = glGetProgramInfoLog(program)
        raise RuntimeError(f"Program link failed: {log}")
    return program


class GLBenchContext:
    """Manages GL resources for benchmarking blit vs shader scaling."""

    def __init__(self, src_w, src_h, dst_w, dst_h):
        from ctypes import c_float, c_void_p
        from OpenGL.GL import (
            glGenTextures, glBindTexture, glTexImage2D, glTexParameteri,
            glGenFramebuffers, glBindFramebuffer, glFramebufferTexture2D,
            glGenVertexArrays, glGenBuffers, glBindBuffer, glBufferData,
            glVertexAttribPointer, glEnableVertexAttribArray, glBindVertexArray,
            GL_TEXTURE_RECTANGLE, GL_TEXTURE_MAG_FILTER, GL_TEXTURE_MIN_FILTER,
            GL_NEAREST, GL_LINEAR, GL_RGBA8, GL_RGBA, GL_UNSIGNED_BYTE,
            GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0,
            GL_ARRAY_BUFFER, GL_STATIC_DRAW, GL_FLOAT, GL_FALSE,
            GL_FRAGMENT_SHADER, GL_VERTEX_SHADER,
        )

        self.src_w, self.src_h = src_w, src_h
        self.dst_w, self.dst_h = dst_w, dst_h
        target = GL_TEXTURE_RECTANGLE

        # Source texture with test pattern
        self.src_tex = glGenTextures(1)
        glBindTexture(target, self.src_tex)
        glTexParameteri(target, GL_TEXTURE_MAG_FILTER, GL_NEAREST)
        glTexParameteri(target, GL_TEXTURE_MIN_FILTER, GL_NEAREST)
        glTexImage2D(target, 0, GL_RGBA8, src_w, src_h, 0, GL_RGBA, GL_UNSIGNED_BYTE, None)

        # Destination texture
        self.dst_tex = glGenTextures(1)
        glBindTexture(target, self.dst_tex)
        glTexParameteri(target, GL_TEXTURE_MAG_FILTER, GL_NEAREST)
        glTexParameteri(target, GL_TEXTURE_MIN_FILTER, GL_NEAREST)
        glTexImage2D(target, 0, GL_RGBA8, dst_w, dst_h, 0, GL_RGBA, GL_UNSIGNED_BYTE, None)

        # Source FBO (for blit read)
        self.src_fbo = glGenFramebuffers(1)
        glBindFramebuffer(GL_FRAMEBUFFER, self.src_fbo)
        glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, target, self.src_tex, 0)

        # Destination FBO (for blit write and shader render)
        self.dst_fbo = glGenFramebuffers(1)
        glBindFramebuffer(GL_FRAMEBUFFER, self.dst_fbo)
        glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, target, self.dst_tex, 0)

        glBindFramebuffer(GL_FRAMEBUFFER, 0)

        # Fullscreen quad VAO
        self.vao = glGenVertexArrays(1)
        glBindVertexArray(self.vao)
        vertices = [-1, -1, 1, -1, -1, 1, 1, 1]
        c_vertices = (c_float * len(vertices))(*vertices)
        self.vbo = glGenBuffers(1)
        glBindBuffer(GL_ARRAY_BUFFER, self.vbo)
        glBufferData(GL_ARRAY_BUFFER, len(vertices) * 4, c_vertices, GL_STATIC_DRAW)
        glVertexAttribPointer(0, 2, GL_FLOAT, GL_FALSE, 0, c_void_p(0))
        glEnableVertexAttribArray(0)
        glBindBuffer(GL_ARRAY_BUFFER, 0)
        glBindVertexArray(0)

        # Compile shaders
        from xpra.opengl.shaders import SOURCE, VERTEX_SHADER
        vs = compile_shader(VERTEX_SHADER, GL_VERTEX_SHADER)
        fs = compile_shader(SOURCE["upscale"], GL_FRAGMENT_SHADER)
        self.program = link_program(vs, fs)

    def upload_pattern(self, pattern):
        """Upload a grayscale float pattern as RGBA8 to the source texture."""
        from OpenGL.GL import (
            glBindTexture, glTexSubImage2D,
            GL_TEXTURE_RECTANGLE, GL_RGBA, GL_UNSIGNED_BYTE,
        )
        w, h = self.src_w, self.src_h
        pixels = bytearray(w * h * 4)
        for i, val in enumerate(pattern):
            v = max(0, min(255, int(val * 255)))
            offset = i * 4
            pixels[offset] = v      # R
            pixels[offset + 1] = v  # G
            pixels[offset + 2] = v  # B
            pixels[offset + 3] = 255  # A
        glBindTexture(GL_TEXTURE_RECTANGLE, self.src_tex)
        glTexSubImage2D(GL_TEXTURE_RECTANGLE, 0, 0, 0, w, h,
                        GL_RGBA, GL_UNSIGNED_BYTE, bytes(pixels))

    def bench_blit(self, frames):
        """Benchmark glBlitFramebuffer with GL_LINEAR."""
        from OpenGL.GL import glFinish, glViewport, GL_LINEAR, GL_COLOR_BUFFER_BIT
        from OpenGL.GL.ARB.framebuffer_object import (
            glBindFramebuffer, glBlitFramebuffer,
            GL_READ_FRAMEBUFFER, GL_DRAW_FRAMEBUFFER,
        )

        sw, sh = self.src_w, self.src_h
        dw, dh = self.dst_w, self.dst_h

        # Warm up
        glBindFramebuffer(GL_READ_FRAMEBUFFER, self.src_fbo)
        glBindFramebuffer(GL_DRAW_FRAMEBUFFER, self.dst_fbo)
        glViewport(0, 0, dw, dh)
        glBlitFramebuffer(0, 0, sw, sh, 0, 0, dw, dh, GL_COLOR_BUFFER_BIT, GL_LINEAR)
        glFinish()

        start = time.monotonic()
        for _ in range(frames):
            glBlitFramebuffer(0, 0, sw, sh, 0, 0, dw, dh, GL_COLOR_BUFFER_BIT, GL_LINEAR)
            glFinish()
        elapsed = time.monotonic() - start
        return elapsed / frames * 1000

    def bench_catmull_rom(self, frames):
        """Benchmark Catmull-Rom shader rendering."""
        from OpenGL.GL import (
            glFinish, glViewport, glUseProgram, glActiveTexture, glBindTexture,
            glTexParameteri, glGetUniformLocation, glUniform1i, glUniform2f,
            glBindVertexArray, glDrawArrays,
            GL_TEXTURE0, GL_TEXTURE_RECTANGLE, GL_TEXTURE_MAG_FILTER,
            GL_TEXTURE_MIN_FILTER, GL_LINEAR, GL_NEAREST, GL_TRIANGLE_STRIP,
        )
        from OpenGL.GL.ARB.framebuffer_object import glBindFramebuffer, GL_FRAMEBUFFER

        sw, sh = self.src_w, self.src_h
        dw, dh = self.dst_w, self.dst_h
        xscale = dw / sw
        yscale = dh / sh
        program = self.program
        target = GL_TEXTURE_RECTANGLE

        # Warm up
        glBindFramebuffer(GL_FRAMEBUFFER, self.dst_fbo)
        glViewport(0, 0, dw, dh)
        glUseProgram(program)
        glActiveTexture(GL_TEXTURE0)
        glBindTexture(target, self.src_tex)
        glTexParameteri(target, GL_TEXTURE_MAG_FILTER, GL_LINEAR)
        glTexParameteri(target, GL_TEXTURE_MIN_FILTER, GL_LINEAR)
        glUniform1i(glGetUniformLocation(program, "fbo"), 0)
        glUniform2f(glGetUniformLocation(program, "viewport_pos"), 0, 0)
        glUniform2f(glGetUniformLocation(program, "scaling"), xscale, yscale)
        glBindVertexArray(self.vao)
        glDrawArrays(GL_TRIANGLE_STRIP, 0, 4)
        glFinish()

        start = time.monotonic()
        for _ in range(frames):
            glDrawArrays(GL_TRIANGLE_STRIP, 0, 4)
            glFinish()
        elapsed = time.monotonic() - start

        # Clean up state
        glBindVertexArray(0)
        glUseProgram(0)
        glTexParameteri(target, GL_TEXTURE_MAG_FILTER, GL_NEAREST)
        glTexParameteri(target, GL_TEXTURE_MIN_FILTER, GL_NEAREST)
        glBindTexture(target, 0)

        return elapsed / frames * 1000

    def readback_grayscale(self):
        """Read back the destination FBO as grayscale floats."""
        from OpenGL.GL import glReadPixels, GL_RGBA, GL_UNSIGNED_BYTE
        from OpenGL.GL.ARB.framebuffer_object import glBindFramebuffer, GL_FRAMEBUFFER

        dw, dh = self.dst_w, self.dst_h
        glBindFramebuffer(GL_FRAMEBUFFER, self.dst_fbo)
        data = glReadPixels(0, 0, dw, dh, GL_RGBA, GL_UNSIGNED_BYTE)
        result = [0.0] * (dw * dh)
        for i in range(dw * dh):
            offset = i * 4
            r = data[offset]
            g = data[offset + 1]
            b = data[offset + 2]
            result[i] = (0.299 * r + 0.587 * g + 0.114 * b) / 255.0
        return result


def main():
    parser = argparse.ArgumentParser(description="Benchmark scaling filters")
    parser.add_argument("--sizes", default="640x480,1280x720",
                        help="Comma-separated source WxH sizes")
    parser.add_argument("--frames", type=int, default=100,
                        help="Number of frames to benchmark")
    parser.add_argument("--scale", type=float, default=1.6,
                        help="Scale factor")
    args = parser.parse_args()

    sizes = []
    for s in args.sizes.split(","):
        w, h = s.strip().split("x")
        sizes.append((int(w), int(h)))

    scale = args.scale
    frames = args.frames

    # Check available backends (GL first — on Linux, must set PYOPENGL_PLATFORM before GL imports)
    have_gl = False
    gl_renderer = ""
    try:
        create_gl_context()
        from OpenGL.GL import glGetString, GL_RENDERER
        gl_renderer = glGetString(GL_RENDERER).decode()
        have_gl = True
    except Exception as e:
        print(f"OpenGL not available ({e}), skipping GPU benchmarks")

    have_cairo = False
    try:
        import cairo
        have_cairo = True
    except ImportError:
        print("Cairo not available, skipping Cairo benchmarks")

    print(f"Benchmark: scale={scale}x, frames={frames}")
    print(f"Ground truth is generated at destination resolution, then downsampled")
    print(f"to source resolution. PSNR measures how well each method recovers the original.")
    if have_gl:
        print(f"GPU: {gl_renderer}")
    print(f"{'Size':>12s}  {'Backend':>30s}  {'ms/frame':>10s}  {'PSNR':>12s}")
    print("-" * 70)

    for src_w, src_h in sizes:
        dst_w = int(src_w * scale)
        dst_h = int(src_h * scale)

        # Ground truth at destination resolution, downsampled to source
        ground_truth = make_test_pattern(dst_w, dst_h)
        source = downsample_box(ground_truth, dst_w, dst_h, src_w, src_h)
        n = dst_w * dst_h

        # CPU Catmull-Rom
        cpu_frames = max(1, frames // 100) if src_w > 640 else max(1, frames // 10)
        cpu_ms, cpu_result = bench_cpu_catmull_rom(source, src_w, src_h, dst_w, dst_h, cpu_frames)
        p = psnr(ground_truth, cpu_result, n)
        print(f"{src_w}x{src_h:>4d}  {'CPU Catmull-Rom':>30s}  {cpu_ms:10.2f}  {p:10.1f} dB")

        if have_cairo:
            src_surface = make_cairo_surface(source, src_w, src_h)

            ms, dst_surface = bench_cairo(src_surface, dst_w, dst_h, scale, scale,
                                          cairo.FILTER_GOOD, frames)
            gray = surface_to_grayscale(dst_surface, dst_w, dst_h)
            p = psnr(ground_truth, gray, n)
            print(f"{'':>12s}  {'Cairo bilinear (GOOD)':>30s}  {ms:10.2f}  {p:10.1f} dB")

            ms, dst_surface = bench_cairo(src_surface, dst_w, dst_h, scale, scale,
                                          cairo.FILTER_BEST, frames)
            gray = surface_to_grayscale(dst_surface, dst_w, dst_h)
            p = psnr(ground_truth, gray, n)
            print(f"{'':>12s}  {'Cairo Catmull-Rom (BEST)':>30s}  {ms:10.2f}  {p:10.1f} dB")

        if have_gl:
            ctx = GLBenchContext(src_w, src_h, dst_w, dst_h)
            ctx.upload_pattern(source)

            ms = ctx.bench_blit(frames)
            ctx.bench_blit(1)
            gray = ctx.readback_grayscale()
            p = psnr(ground_truth, gray, n)
            print(f"{'':>12s}  {'OpenGL bilinear (blit)':>30s}  {ms:10.2f}  {p:10.1f} dB")

            ms = ctx.bench_catmull_rom(frames)
            ctx.bench_catmull_rom(1)
            gray = ctx.readback_grayscale()
            p = psnr(ground_truth, gray, n)
            print(f"{'':>12s}  {'OpenGL Catmull-Rom (shader)':>30s}  {ms:10.2f}  {p:10.1f} dB")

        print()


if __name__ == "__main__":
    main()
