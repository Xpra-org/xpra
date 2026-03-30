#!/usr/bin/env python3
# ABOUTME: Benchmarks scaling quality and throughput for Cairo and OpenGL renderers.
# ABOUTME: Compares bilinear, Catmull-Rom, sigmoid upscaling, and anti-ringing variants.

"""
Benchmark scaling quality and throughput for Cairo (bilinear/Catmull-Rom)
and OpenGL (bilinear blit/Catmull-Rom/sigmoid/anti-ringing shaders).

Usage:
    python3 tests/scripts/benchmark_scaling.py [--sizes 640x480,1920x1080] [--frames 100] [--scale 1.6]

Detects available backends automatically:
  - Cairo: requires pycairo
  - OpenGL: requires PyOpenGL + GPU (EGL device platform on Linux, WGL on Windows)
  - CPU reference: pure Python Catmull-Rom (always available)
"""

import argparse
import math
import multiprocessing
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


# Sigmoid upscaling constants (mpv/libplacebo defaults)
SIG_CENTER = 0.75
SIG_SLOPE = 6.5
SIG_OFFSET = 1.0 / (1.0 + math.exp(SIG_SLOPE * SIG_CENTER))
SIG_SCALE = 1.0 / (1.0 + math.exp(SIG_SLOPE * (SIG_CENTER - 1.0))) - SIG_OFFSET

# Anti-ringing clamp strength (libplacebo sweet spot per Artoriuz's evaluation)
AR_STRENGTH = 0.8

# RCAS sharpening strength (0.0 = maximum, 1.0 = minimum; 0.5 is conservative for text)
CAS_SHARPNESS = 0.5


def sigmoidize(x):
    """Forward sigmoid: linear [0,1] -> sigmoid space."""
    x = max(0.0, min(1.0, x))
    return SIG_CENTER - math.log(1.0 / (x * SIG_SCALE + SIG_OFFSET) - 1.0) / SIG_SLOPE


def unsigmoidize(x):
    """Inverse sigmoid: sigmoid space -> linear."""
    return (1.0 / SIG_SCALE) / (1.0 + math.exp(SIG_SLOPE * (SIG_CENTER - x))) - SIG_OFFSET / SIG_SCALE


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


def catmull_rom_enhanced_cpu(src, src_w, src_h, dst_w, dst_h, use_sigmoid=False, ar_strength=0.0):
    """
    CPU reference: 16-tap Catmull-Rom with optional sigmoid and anti-ringing.
    Uses direct 4x4 texel sampling (no bilinear trick) for sigmoid correctness.
    """
    dst = [0.0] * (dst_w * dst_h)
    sx = src_w / dst_w
    sy = src_h / dst_h

    def clamp_get(r, c):
        r = max(0, min(src_h - 1, r))
        c = max(0, min(src_w - 1, c))
        return src[r * src_w + c]

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

            icx = int(cx - 0.5)
            icy = int(cy - 0.5)

            val = 0.0
            for j in range(4):
                for i in range(4):
                    s = clamp_get(icy + j - 1, icx + i - 1)
                    if use_sigmoid:
                        s = sigmoidize(s)
                    val += s * wx[i] * wy[j]

            if use_sigmoid:
                val = unsigmoidize(val)

            if ar_strength > 0:
                n00 = clamp_get(icy, icx)
                n10 = clamp_get(icy, icx + 1)
                n01 = clamp_get(icy + 1, icx)
                n11 = clamp_get(icy + 1, icx + 1)
                lo = min(n00, n10, n01, n11)
                hi = max(n00, n10, n01, n11)
                clamped = max(lo, min(hi, val))
                val = val + ar_strength * (clamped - val)

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


def ssim_if_available(ref, test, w, h):
    """Compute SSIM using numpy only. Returns None if numpy is unavailable."""
    try:
        import numpy as np
    except ImportError:
        return None

    a = np.array(ref, dtype=np.float64).reshape(h, w)
    b = np.array(test, dtype=np.float64).reshape(h, w)

    # SSIM constants (Wang et al. 2004), data_range=1.0
    C1 = (0.01) ** 2
    C2 = (0.03) ** 2
    win = 7

    # Box-filter mean via cumulative sums (no scipy needed)
    def box_mean(img):
        cs = np.cumsum(np.cumsum(img, axis=0), axis=1)
        padded = np.zeros((img.shape[0] + 1, img.shape[1] + 1))
        padded[1:, 1:] = cs
        r = win // 2
        y0 = np.clip(np.arange(img.shape[0]) - r, 0, img.shape[0])
        y1 = np.clip(np.arange(img.shape[0]) - r + win, 0, img.shape[0])
        x0 = np.clip(np.arange(img.shape[1]) - r, 0, img.shape[1])
        x1 = np.clip(np.arange(img.shape[1]) - r + win, 0, img.shape[1])
        counts = np.outer(y1 - y0, x1 - x0).astype(np.float64)
        sums = (padded[np.ix_(y1, x1)] - padded[np.ix_(y0, x1)]
                - padded[np.ix_(y1, x0)] + padded[np.ix_(y0, x0)])
        return sums / counts

    mu_a = box_mean(a)
    mu_b = box_mean(b)
    sigma_a2 = box_mean(a * a) - mu_a * mu_a
    sigma_b2 = box_mean(b * b) - mu_b * mu_b
    sigma_ab = box_mean(a * b) - mu_a * mu_b

    num = (2 * mu_a * mu_b + C1) * (2 * sigma_ab + C2)
    den = (mu_a ** 2 + mu_b ** 2 + C1) * (sigma_a2 + sigma_b2 + C2)
    return float(np.mean(num / den))


def overshoot(src, src_w, src_h, result, dst_w, dst_h):
    """
    Measure ringing as mean overshoot beyond the nearest 4 source texel range.
    Returns (mean_overshoot, max_overshoot) in [0,1] scale.
    Uses numpy when available for speed.
    """
    try:
        import numpy as np
        return _overshoot_numpy(src, src_w, src_h, result, dst_w, dst_h, np)
    except ImportError:
        return _overshoot_python(src, src_w, src_h, result, dst_w, dst_h)


def _overshoot_numpy(src, src_w, src_h, result, dst_w, dst_h, np):
    src_arr = np.array(src, dtype=np.float64).reshape(src_h, src_w)
    res_arr = np.array(result, dtype=np.float64).reshape(dst_h, dst_w)
    sx = src_w / dst_w
    sy = src_h / dst_h

    dx = np.arange(dst_w)
    dy = np.arange(dst_h)
    coord_x = (dx + 0.5) * sx
    coord_y = (dy + 0.5) * sy
    icx = np.floor(coord_x - 0.5).astype(int)
    icy = np.floor(coord_y - 0.5).astype(int)

    # Clamp indices to valid range
    cx0 = np.clip(icx, 0, src_w - 1)
    cx1 = np.clip(icx + 1, 0, src_w - 1)
    cy0 = np.clip(icy, 0, src_h - 1)
    cy1 = np.clip(icy + 1, 0, src_h - 1)

    # 4 nearest texels via outer indexing
    n00 = src_arr[np.ix_(cy0, cx0)]
    n10 = src_arr[np.ix_(cy0, cx1)]
    n01 = src_arr[np.ix_(cy1, cx0)]
    n11 = src_arr[np.ix_(cy1, cx1)]

    lo = np.minimum(np.minimum(n00, n10), np.minimum(n01, n11))
    hi = np.maximum(np.maximum(n00, n10), np.maximum(n01, n11))

    over = np.maximum(0.0, res_arr - hi) + np.maximum(0.0, lo - res_arr)
    return float(np.mean(over)), float(np.max(over))


def _overshoot_python(src, src_w, src_h, result, dst_w, dst_h):
    sx = src_w / dst_w
    sy = src_h / dst_h
    total = 0.0
    peak = 0.0

    def clamp_get(r, c):
        r = max(0, min(src_h - 1, r))
        c = max(0, min(src_w - 1, c))
        return src[r * src_w + c]

    for dy in range(dst_h):
        for dx in range(dst_w):
            coord_x = (dx + 0.5) * sx
            coord_y = (dy + 0.5) * sy
            icx = int(math.floor(coord_x - 0.5))
            icy = int(math.floor(coord_y - 0.5))

            n00 = clamp_get(icy, icx)
            n10 = clamp_get(icy, icx + 1)
            n01 = clamp_get(icy + 1, icx)
            n11 = clamp_get(icy + 1, icx + 1)
            lo = min(n00, n10, n01, n11)
            hi = max(n00, n10, n01, n11)

            val = result[dy * dst_w + dx]
            over = max(0.0, val - hi) + max(0.0, lo - val)
            total += over
            if over > peak:
                peak = over

    n = dst_w * dst_h
    return total / n, peak


def bench_cpu_catmull_rom(src, src_w, src_h, dst_w, dst_h, frames):
    """Benchmark CPU Catmull-Rom and return (ms_per_frame, result)."""
    result = catmull_rom_2d_cpu(src, src_w, src_h, dst_w, dst_h)
    start = time.monotonic()
    for _ in range(frames):
        result = catmull_rom_2d_cpu(src, src_w, src_h, dst_w, dst_h)
    elapsed = time.monotonic() - start
    return elapsed / frames * 1000, result


def _run_cpu_bench(args):
    """Top-level wrapper for multiprocessing (must be picklable)."""
    label, src_data, sw, sh, dw, dh, nframes, kwargs = args
    if kwargs:
        ms, result = bench_cpu_enhanced(src_data, sw, sh, dw, dh, nframes, **kwargs)
    else:
        ms, result = bench_cpu_catmull_rom(src_data, sw, sh, dw, dh, nframes)
    return label, ms, result


def bench_cpu_enhanced(src, src_w, src_h, dst_w, dst_h, frames, **kwargs):
    """Benchmark catmull_rom_enhanced_cpu and return (ms_per_frame, result)."""
    result = catmull_rom_enhanced_cpu(src, src_w, src_h, dst_w, dst_h, **kwargs)
    start = time.monotonic()
    for _ in range(frames):
        result = catmull_rom_enhanced_cpu(src, src_w, src_h, dst_w, dst_h, **kwargs)
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
    """GL 3.3 context via WGL ARB bootstrap, with legacy fallback (Windows).

    On x64 Windows the legacy wglCreateContext often returns GDI Generic (GL 1.1).
    The standard fix is a two-phase bootstrap: create a throwaway legacy context to
    load the ARB extension pointers, then use wglCreateContextAttribsARB to request
    GL 3.3 core profile on a fresh window.
    """
    import ctypes
    from ctypes import sizeof, byref, c_void_p, c_int, c_float, POINTER

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

    def make_window(title):
        hwnd = user32.CreateWindowExA(
            0, atom, title,
            0x00000000 | 0x00080000,  # WS_OVERLAPPED | WS_SYSMENU
            -2147483648, -2147483648, 1, 1,  # CW_USEDEFAULT
            None, None, h_inst, None,
        )
        if not hwnd:
            raise RuntimeError("CreateWindowExA failed")
        return hwnd, user32.GetDC(hwnd)

    def make_basic_pfd():
        pfd = PIXELFORMATDESCRIPTOR()
        pfd.nSize = sizeof(PIXELFORMATDESCRIPTOR)
        pfd.nVersion = 1
        pfd.dwFlags = 0x04 | 0x20 | 0x01  # PFD_DRAW_TO_WINDOW | PFD_SUPPORT_OPENGL | PFD_DOUBLEBUFFER
        pfd.iPixelType = 0  # PFD_TYPE_RGBA
        pfd.cColorBits = 32
        pfd.cDepthBits = 24
        pfd.cStencilBits = 2
        return pfd

    def set_basic_pixel_format(hdc):
        pfd = make_basic_pfd()
        pf = gdi32.ChoosePixelFormat(hdc, byref(pfd))
        if not pf:
            raise RuntimeError("ChoosePixelFormat failed")
        gdi32.SetPixelFormat(hdc, pf, byref(pfd))

    # Phase 1: bootstrap context to load ARB extension pointers.
    # The legacy wglCreateContext may return GDI Generic on x64, but that's
    # enough to call wglGetProcAddress for the ARB functions.
    boot_hwnd, boot_hdc = make_window(b"Xpra GL Bootstrap")
    set_basic_pixel_format(boot_hdc)
    boot_hglrc = opengl32.wglCreateContext(boot_hdc)
    if not boot_hglrc:
        raise RuntimeError("wglCreateContext failed (bootstrap)")
    opengl32.wglMakeCurrent(boot_hdc, boot_hglrc)

    opengl32.wglGetProcAddress.restype = c_void_p
    opengl32.wglGetProcAddress.argtypes = [ctypes.c_char_p]
    choose_pf_ptr = opengl32.wglGetProcAddress(b"wglChoosePixelFormatARB")
    create_ctx_ptr = opengl32.wglGetProcAddress(b"wglCreateContextAttribsARB")

    if choose_pf_ptr and create_ctx_ptr:
        # Phase 2: destroy bootstrap, create real context via ARB extensions.
        # SetPixelFormat can only be called once per window, so we need a fresh one.
        CHOOSE_PF_T = ctypes.WINFUNCTYPE(
            c_int, c_void_p, POINTER(c_int), POINTER(c_float),
            ctypes.c_uint, POINTER(c_int), POINTER(ctypes.c_uint))
        CREATE_CTX_T = ctypes.WINFUNCTYPE(
            c_void_p, c_void_p, c_void_p, POINTER(c_int))
        wglChoosePixelFormatARB = CHOOSE_PF_T(choose_pf_ptr)
        wglCreateContextAttribsARB = CREATE_CTX_T(create_ctx_ptr)

        opengl32.wglMakeCurrent(None, None)
        opengl32.wglDeleteContext(boot_hglrc)
        user32.ReleaseDC(boot_hwnd, boot_hdc)
        user32.DestroyWindow(boot_hwnd)

        hwnd, hdc = make_window(b"Xpra Benchmark GL")

        # Request a hardware-accelerated RGBA pixel format
        WGL_DRAW_TO_WINDOW_ARB   = 0x2001
        WGL_ACCELERATION_ARB     = 0x2003
        WGL_SUPPORT_OPENGL_ARB   = 0x2010
        WGL_DOUBLE_BUFFER_ARB    = 0x2011
        WGL_PIXEL_TYPE_ARB       = 0x2013
        WGL_COLOR_BITS_ARB       = 0x2014
        WGL_DEPTH_BITS_ARB       = 0x2022
        WGL_STENCIL_BITS_ARB     = 0x2023
        WGL_FULL_ACCELERATION_ARB = 0x2027
        WGL_TYPE_RGBA_ARB        = 0x202B
        pf_attribs = (c_int * 19)(
            WGL_DRAW_TO_WINDOW_ARB, 1,
            WGL_SUPPORT_OPENGL_ARB, 1,
            WGL_DOUBLE_BUFFER_ARB, 1,
            WGL_PIXEL_TYPE_ARB, WGL_TYPE_RGBA_ARB,
            WGL_COLOR_BITS_ARB, 32,
            WGL_DEPTH_BITS_ARB, 24,
            WGL_STENCIL_BITS_ARB, 2,
            WGL_ACCELERATION_ARB, WGL_FULL_ACCELERATION_ARB,
            0,
        )
        pf_id = c_int()
        num_formats = ctypes.c_uint()
        ok = wglChoosePixelFormatARB(hdc, pf_attribs, None, 1,
                                     byref(pf_id), byref(num_formats))

        hglrc = None
        if ok and num_formats.value > 0:
            pfd = make_basic_pfd()
            gdi32.SetPixelFormat(hdc, pf_id.value, byref(pfd))

            # Request GL 3.3 core profile
            WGL_CONTEXT_MAJOR_VERSION_ARB    = 0x2091
            WGL_CONTEXT_MINOR_VERSION_ARB    = 0x2092
            WGL_CONTEXT_PROFILE_MASK_ARB     = 0x9126
            WGL_CONTEXT_CORE_PROFILE_BIT_ARB = 0x00000001
            ctx_attribs = (c_int * 7)(
                WGL_CONTEXT_MAJOR_VERSION_ARB, 3,
                WGL_CONTEXT_MINOR_VERSION_ARB, 3,
                WGL_CONTEXT_PROFILE_MASK_ARB, WGL_CONTEXT_CORE_PROFILE_BIT_ARB,
                0,
            )
            hglrc = wglCreateContextAttribsARB(hdc, None, ctx_attribs)

        if not hglrc:
            # ARB pixel format or context creation failed; fall back to legacy
            user32.ReleaseDC(hwnd, hdc)
            user32.DestroyWindow(hwnd)
            hwnd, hdc = make_window(b"Xpra Benchmark GL")
            set_basic_pixel_format(hdc)
            hglrc = opengl32.wglCreateContext(hdc)
            if not hglrc:
                raise RuntimeError("wglCreateContext failed")

        opengl32.wglMakeCurrent(hdc, hglrc)
        _create_wgl_context._refs = (_wnd_proc_cb, hwnd, hdc, hglrc,
                                     wglChoosePixelFormatARB, wglCreateContextAttribsARB)
    else:
        # No ARB extensions — keep the bootstrap context as-is.
        # This works on ARM64 where the legacy path returns a modern context.
        _create_wgl_context._refs = (_wnd_proc_cb, boot_hwnd, boot_hdc, boot_hglrc)


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


# --- GLSL shader variants for benchmarking ---
# All variants use the single uniform-controlled shader from shaders.py.
# Different variants are achieved by setting use_sigmoid and ar_strength uniforms
# on the single compiled program at draw time.


# RCAS: Robust Contrast-Adaptive Sharpening (post-process, 5-tap cross pattern).
# Ported from AMD FidelityFX FSR 1.0 (MIT license).
# Reference: https://gist.github.com/agyild/82219c545228d70c5604f865ce0b0ce5
# Operates on an already-upscaled image in a second pass.
RCAS_SHADER = f"""
#version 330 core
layout(origin_upper_left) in vec4 gl_FragCoord;
uniform sampler2DRect src;
layout(location = 0) out vec4 frag_color;

// Approximate medium-precision reciprocal (AMD APrxMedRcpF1):
// bit-hack initial estimate + one Newton-Raphson refinement.
float rcpAprx(float a) {{
    float b = uintBitsToFloat(uint(0x7ef19fff) - floatBitsToUint(a));
    return b * (-b * a + 2.0);
}}

void main() {{
    // Flip y: origin_upper_left puts y=0 at screen top, but the FBO texture
    // follows GL convention with y=0 at bottom.
    vec2 pos = gl_FragCoord.xy;
    pos.y = float(textureSize(src).y) - pos.y;

    // 5-tap cross pattern on the upscaled image
    vec3 b = texture(src, pos + vec2( 0.0, -1.0)).rgb;
    vec3 d = texture(src, pos + vec2(-1.0,  0.0)).rgb;
    vec3 e = texture(src, pos).rgb;
    vec3 f = texture(src, pos + vec2( 1.0,  0.0)).rgb;
    vec3 h = texture(src, pos + vec2( 0.0,  1.0)).rgb;

    // Luma of the cross (BT.709 weights)
    const vec3 LUMA = vec3(0.2126, 0.7152, 0.0722);
    float bL = dot(b, LUMA);
    float dL = dot(d, LUMA);
    float eL = dot(e, LUMA);
    float fL = dot(f, LUMA);
    float hL = dot(h, LUMA);

    // Min/max of the 4 neighbors (excluding center)
    float mn1L = min(min(bL, dL), min(fL, hL));
    float mx1L = max(max(bL, dL), max(fL, hL));

    // Analytically solve for max negative weight before any pixel clips.
    // hitMin: weight limit before output goes below 0
    // hitMax: weight limit before output goes above 1
    float hitMinL = min(mn1L, eL) / (4.0 * mx1L);
    float hitMaxL = (1.0 - max(mx1L, eL)) / (4.0 * mn1L - 4.0);
    float lobeL = max(-hitMinL, hitMaxL);

    // FSR_RCAS_LIMIT = 0.25 - 1/16 = 0.1875
    float lobe = max(-0.1875, min(lobeL, 0.0)) * exp2(-clamp({CAS_SHARPNESS}, 0.0, 2.0));

    // Noise detection: reduce sharpening in noisy/dithered areas
    float nz = 0.25 * (bL + dL + fL + hL) - eL;
    float range = max(max(max(bL, dL), max(eL, fL)), hL)
                - min(min(min(bL, dL), min(eL, fL)), hL);
    nz = clamp(abs(nz) * rcpAprx(max(range, 1.0 / 65536.0)), 0.0, 1.0);
    lobe *= (-0.5 * nz + 1.0);

    // Final resolve with approximate reciprocal
    float rcpW = rcpAprx(4.0 * lobe + 1.0);
    frag_color = vec4(
        clamp((lobe * (b.r + d.r + f.r + h.r) + e.r) * rcpW, 0.0, 1.0),
        clamp((lobe * (b.g + d.g + f.g + h.g) + e.g) * rcpW, 0.0, 1.0),
        clamp((lobe * (b.b + d.b + f.b + h.b) + e.b) * rcpW, 0.0, 1.0),
        1.0);
}}
"""


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

        # Compile shaders: one upscale program (uniforms control variant) + RCAS
        from xpra.opengl.shaders import SOURCE, VERTEX_SHADER
        vs = compile_shader(VERTEX_SHADER, GL_VERTEX_SHADER)
        fs = compile_shader(SOURCE["upscale"], GL_FRAGMENT_SHADER)
        self.program = link_program(vs, fs)

        fs_rcas = compile_shader(RCAS_SHADER, GL_FRAGMENT_SHADER)
        self.program_rcas = link_program(vs, fs_rcas)

        # Second destination texture/FBO for two-pass CAS pipeline
        self.cas_tex = glGenTextures(1)
        glBindTexture(target, self.cas_tex)
        glTexParameteri(target, GL_TEXTURE_MAG_FILTER, GL_NEAREST)
        glTexParameteri(target, GL_TEXTURE_MIN_FILTER, GL_NEAREST)
        glTexImage2D(target, 0, GL_RGBA8, dst_w, dst_h, 0, GL_RGBA, GL_UNSIGNED_BYTE, None)

        self.cas_fbo = glGenFramebuffers(1)
        glBindFramebuffer(GL_FRAMEBUFFER, self.cas_fbo)
        glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, target, self.cas_tex, 0)
        glBindFramebuffer(GL_FRAMEBUFFER, 0)

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

    def bench_upscale(self, frames, use_sigmoid=False, ar_strength=0.0):
        """Benchmark the upscale shader with given uniform settings."""
        from OpenGL.GL import (
            glFinish, glViewport, glUseProgram, glActiveTexture, glBindTexture,
            glTexParameteri, glGetUniformLocation, glUniform1i, glUniform1f, glUniform2f,
            glBindVertexArray, glDrawArrays,
            GL_TEXTURE0, GL_TEXTURE_RECTANGLE, GL_TEXTURE_MAG_FILTER,
            GL_TEXTURE_MIN_FILTER, GL_NEAREST, GL_TRIANGLE_STRIP,
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
        glTexParameteri(target, GL_TEXTURE_MAG_FILTER, GL_NEAREST)
        glTexParameteri(target, GL_TEXTURE_MIN_FILTER, GL_NEAREST)
        glUniform1i(glGetUniformLocation(program, "fbo"), 0)
        glUniform2f(glGetUniformLocation(program, "viewport_pos"), 0, 0)
        glUniform2f(glGetUniformLocation(program, "scaling"), xscale, yscale)
        glUniform1i(glGetUniformLocation(program, "use_sigmoid"), int(use_sigmoid))
        glUniform1f(glGetUniformLocation(program, "ar_strength"), ar_strength)
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
        glBindTexture(target, 0)

        return elapsed / frames * 1000

    def bench_two_pass(self, frames, use_sigmoid=False, ar_strength=0.0):
        """Benchmark upscale + RCAS sharpening (two-pass pipeline)."""
        from OpenGL.GL import (
            glFinish, glViewport, glUseProgram, glActiveTexture, glBindTexture,
            glTexParameteri, glGetUniformLocation, glUniform1i, glUniform1f, glUniform2f,
            glBindVertexArray, glDrawArrays,
            GL_TEXTURE0, GL_TEXTURE_RECTANGLE, GL_TEXTURE_MAG_FILTER,
            GL_TEXTURE_MIN_FILTER, GL_NEAREST, GL_TRIANGLE_STRIP,
        )
        from OpenGL.GL.ARB.framebuffer_object import glBindFramebuffer, GL_FRAMEBUFFER

        sw, sh = self.src_w, self.src_h
        dw, dh = self.dst_w, self.dst_h
        xscale = dw / sw
        yscale = dh / sh
        program = self.program
        target = GL_TEXTURE_RECTANGLE

        # Warm up: pass 1 (upscale src → dst_fbo)
        glBindFramebuffer(GL_FRAMEBUFFER, self.dst_fbo)
        glViewport(0, 0, dw, dh)
        glUseProgram(program)
        glActiveTexture(GL_TEXTURE0)
        glBindTexture(target, self.src_tex)
        glTexParameteri(target, GL_TEXTURE_MAG_FILTER, GL_NEAREST)
        glTexParameteri(target, GL_TEXTURE_MIN_FILTER, GL_NEAREST)
        glUniform1i(glGetUniformLocation(program, "fbo"), 0)
        glUniform2f(glGetUniformLocation(program, "viewport_pos"), 0, 0)
        glUniform2f(glGetUniformLocation(program, "scaling"), xscale, yscale)
        glUniform1i(glGetUniformLocation(program, "use_sigmoid"), int(use_sigmoid))
        glUniform1f(glGetUniformLocation(program, "ar_strength"), ar_strength)
        glBindVertexArray(self.vao)
        glDrawArrays(GL_TRIANGLE_STRIP, 0, 4)

        # Warm up: pass 2 (CAS dst_tex → cas_fbo)
        glBindFramebuffer(GL_FRAMEBUFFER, self.cas_fbo)
        glUseProgram(self.program_rcas)
        glBindTexture(target, self.dst_tex)
        glTexParameteri(target, GL_TEXTURE_MAG_FILTER, GL_NEAREST)
        glTexParameteri(target, GL_TEXTURE_MIN_FILTER, GL_NEAREST)
        glUniform1i(glGetUniformLocation(self.program_rcas, "src"), 0)
        glDrawArrays(GL_TRIANGLE_STRIP, 0, 4)
        glFinish()

        start = time.monotonic()
        for _ in range(frames):
            # Pass 1: upscale
            glBindFramebuffer(GL_FRAMEBUFFER, self.dst_fbo)
            glUseProgram(program)
            glBindTexture(target, self.src_tex)
            glDrawArrays(GL_TRIANGLE_STRIP, 0, 4)

            # Pass 2: CAS sharpen
            glBindFramebuffer(GL_FRAMEBUFFER, self.cas_fbo)
            glUseProgram(self.program_rcas)
            glBindTexture(target, self.dst_tex)
            glDrawArrays(GL_TRIANGLE_STRIP, 0, 4)

            glFinish()
        elapsed = time.monotonic() - start

        # Clean up
        glBindVertexArray(0)
        glUseProgram(0)
        glTexParameteri(target, GL_TEXTURE_MAG_FILTER, GL_NEAREST)
        glTexParameteri(target, GL_TEXTURE_MIN_FILTER, GL_NEAREST)
        glBindTexture(target, 0)

        return elapsed / frames * 1000

    def readback_cas_grayscale(self):
        """Read back the CAS FBO as grayscale floats."""
        from OpenGL.GL import glReadPixels, GL_RGBA, GL_UNSIGNED_BYTE
        from OpenGL.GL.ARB.framebuffer_object import glBindFramebuffer, GL_FRAMEBUFFER

        dw, dh = self.dst_w, self.dst_h
        glBindFramebuffer(GL_FRAMEBUFFER, self.cas_fbo)
        data = glReadPixels(0, 0, dw, dh, GL_RGBA, GL_UNSIGNED_BYTE)
        result = [0.0] * (dw * dh)
        for i in range(dw * dh):
            offset = i * 4
            r = data[offset]
            g = data[offset + 1]
            b = data[offset + 2]
            result[i] = (0.299 * r + 0.587 * g + 0.114 * b) / 255.0
        return result

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
        from OpenGL.GL import glGetString, GL_RENDERER, GL_VERSION
        gl_renderer = glGetString(GL_RENDERER).decode()
        gl_version_str = glGetString(GL_VERSION).decode()
        # Parse major.minor from version string (e.g. "4.6.0 NVIDIA 535.129.03")
        import re
        m = re.match(r"(\d+)\.(\d+)", gl_version_str)
        gl_major, gl_minor = (int(m.group(1)), int(m.group(2))) if m else (0, 0)
        if "GDI Generic" in gl_renderer:
            print(f"OpenGL renderer is GDI Generic (no GPU acceleration), skipping GPU benchmarks")
            print(f"  (this typically happens over RDP or when no GPU driver is installed)")
        elif gl_major < 3 or (gl_major == 3 and gl_minor < 3):
            print(f"OpenGL {gl_version_str} ({gl_renderer}) is below 3.3, skipping GPU benchmarks")
        else:
            # Shaders use #version 330 core — verify we have a core profile context
            from OpenGL.GL import glGetIntegerv, GL_CONTEXT_PROFILE_MASK
            GL_CONTEXT_CORE_PROFILE_BIT = 0x00000001
            profile = glGetIntegerv(GL_CONTEXT_PROFILE_MASK)
            if not (profile & GL_CONTEXT_CORE_PROFILE_BIT):
                print(f"OpenGL {gl_version_str} ({gl_renderer}) is compatibility profile,")
                print(f"  skipping GPU benchmarks (shaders require core profile)")
            else:
                have_gl = True
    except Exception as e:
        print(f"OpenGL not available ({e}), skipping GPU benchmarks")

    have_cairo = False
    try:
        import cairo
        have_cairo = True
    except ImportError:
        print("Cairo not available, skipping Cairo benchmarks")

    # CPU info
    cpu_name = ""
    try:
        with open("/proc/cpuinfo") as f:
            for line in f:
                if line.startswith("model name"):
                    cpu_name = line.split(":", 1)[1].strip()
                    break
    except OSError:
        pass

    print(f"Benchmark: scale={scale}x, frames={frames}")
    print(f"Ground truth is generated at destination resolution, then downsampled")
    print(f"to source resolution. Metrics:")
    print(f"  PSNR: peak signal-to-noise ratio (higher = closer to ground truth)")
    print(f"  Overshoot: mean amount output exceeds nearest source texel range (ringing severity)")
    if ssim_if_available([0.0, 1.0], [0.0, 1.0], 2, 1) is not None:
        print(f"  SSIM: structural similarity index (higher = perceptually closer to ground truth)")
    if cpu_name:
        print(f"CPU: {cpu_name} ({multiprocessing.cpu_count()} cores, {multiprocessing.cpu_count() // 4} workers)")
    if have_gl:
        print(f"GPU: {gl_renderer}")
    have_ssim_pkg = ssim_if_available([0.0, 1.0], [0.0, 1.0], 2, 1) is not None
    ssim_hdr = "      SSIM" if have_ssim_pkg else ""
    print(f"{'Size':>12s}  {'Backend':>40s}  {'ms/frame':>10s}  {'PSNR':>8s}  {'Overshoot':>10s}{ssim_hdr}")
    print("-" * (88 + (10 if have_ssim_pkg else 0)))

    for src_w, src_h in sizes:
        dst_w = int(src_w * scale)
        dst_h = int(src_h * scale)

        # Ground truth at destination resolution, downsampled to source
        ground_truth = make_test_pattern(dst_w, dst_h)
        source = downsample_box(ground_truth, dst_w, dst_h, src_w, src_h)
        n = dst_w * dst_h

        # CPU benchmarks (reduced frames for large sizes, parallelized)
        cpu_frames = max(1, frames // 100) if src_w > 640 else max(1, frames // 10)

        have_ssim = ssim_if_available([0.0, 1.0], [0.0, 1.0], 2, 1) is not None

        def print_result(label, ms, result, size_prefix=""):
            p = psnr(ground_truth, result, n)
            mean_os, _ = overshoot(source, src_w, src_h, result, dst_w, dst_h)
            prefix = f"{size_prefix:>12s}" if size_prefix else f"{'':>12s}"
            line = f"{prefix}  {label:>40s}  {ms:10.2f}  {p:6.1f}dB  {mean_os:10.6f}"
            if have_ssim:
                s = ssim_if_available(ground_truth, result, dst_w, dst_h)
                line += f"  {s:.6f}"
            print(line)

        # Run all 4 CPU variants in parallel
        cpu_workers = max(1, multiprocessing.cpu_count() // 4)
        cpu_args = [
            ("CPU Catmull-Rom", source, src_w, src_h, dst_w, dst_h, cpu_frames, {}),
            ("CPU CR + anti-ringing", source, src_w, src_h, dst_w, dst_h, cpu_frames,
             {"ar_strength": AR_STRENGTH}),
            ("CPU CR + sigmoid", source, src_w, src_h, dst_w, dst_h, cpu_frames,
             {"use_sigmoid": True}),
            ("CPU CR + sigmoid + anti-ringing", source, src_w, src_h, dst_w, dst_h, cpu_frames,
             {"use_sigmoid": True, "ar_strength": AR_STRENGTH}),
        ]

        with multiprocessing.Pool(min(cpu_workers, len(cpu_args))) as pool:
            cpu_results = pool.map(_run_cpu_bench, cpu_args)

        for i, (label, ms, result) in enumerate(cpu_results):
            print_result(label, ms, result, f"{src_w}x{src_h}" if i == 0 else "")

        if have_cairo:
            src_surface = make_cairo_surface(source, src_w, src_h)

            ms, dst_surface = bench_cairo(src_surface, dst_w, dst_h, scale, scale,
                                          cairo.FILTER_GOOD, frames)
            gray = surface_to_grayscale(dst_surface, dst_w, dst_h)
            print_result("Cairo bilinear (GOOD)", ms, gray)

            ms, dst_surface = bench_cairo(src_surface, dst_w, dst_h, scale, scale,
                                          cairo.FILTER_BEST, frames)
            gray = surface_to_grayscale(dst_surface, dst_w, dst_h)
            print_result("Cairo Catmull-Rom (BEST)", ms, gray)

        if have_gl:
            ctx = GLBenchContext(src_w, src_h, dst_w, dst_h)
            ctx.upload_pattern(source)

            def bench_gl(label, **kwargs):
                ms = ctx.bench_upscale(frames, **kwargs)
                ctx.bench_upscale(1, **kwargs)  # final render for readback
                gray = ctx.readback_grayscale()
                print_result(label, ms, gray)

            def bench_gl_cas(label, **kwargs):
                ms = ctx.bench_two_pass(frames, **kwargs)
                ctx.bench_two_pass(1, **kwargs)  # final render
                gray = ctx.readback_cas_grayscale()
                print_result(label, ms, gray)

            # Bilinear blit (uses glBlitFramebuffer, not the shader)
            ms = ctx.bench_blit(frames)
            ctx.bench_blit(1)
            gray = ctx.readback_grayscale()
            print_result("OpenGL bilinear (blit)", ms, gray)

            bench_gl("OpenGL Catmull-Rom")  # no sigmoid, no AR = plain CR (16-tap)
            bench_gl("OpenGL CR + anti-ringing", ar_strength=AR_STRENGTH)
            bench_gl("OpenGL CR + sigmoid", use_sigmoid=True)
            bench_gl("OpenGL CR + sigmoid + anti-ringing", use_sigmoid=True, ar_strength=AR_STRENGTH)
            bench_gl_cas("OpenGL CR + CAS")
            bench_gl_cas("OpenGL CR + sigmoid + AR + CAS", use_sigmoid=True, ar_strength=AR_STRENGTH)

        print()


if __name__ == "__main__":
    multiprocessing.freeze_support()
    main()
