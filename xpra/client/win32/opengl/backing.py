# This file is part of Xpra.
# Copyright (C) 2025 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from ctypes.wintypes import HWND, HDC
from collections.abc import Callable

from xpra.opengl.backing import GLWindowBackingBase
from xpra.platform.win32.common import SwapBuffers
from xpra.platform.win32.glwin32 import wglMakeCurrent
from xpra.platform.win32.gl_context import WGLContext
from xpra.log import Logger

log = Logger("opengl", "paint", "win32")


class WGLPaintContext:
    """
    A minimal WGL "window context" bound to an existing `HWND`.

    Unlike `xpra.platform.win32.gl_context.WGLWindowContext`, this does *not*
    call `BeginPaint`/`EndPaint`: the win32 client already brackets its own
    `WM_PAINT` handling with those, and regular (server-driven) draws happen
    outside of any `WM_PAINT`. We only need to make the GL context current and
    swap the buffers on the same device context the context was created with.
    """

    def __init__(self, hdc: HDC, context):
        self.hdc = hdc
        self.context = context

    def __enter__(self):
        log("wglMakeCurrent(%#x, %#x)", self.hdc or 0, self.context or 0)
        if not wglMakeCurrent(self.hdc, self.context):
            raise RuntimeError("wglMakeCurrent failed")
        return self

    def __exit__(self, *_args):
        wglMakeCurrent(0, 0)

    def swap_buffers(self) -> None:
        log("swap_buffers: SwapBuffers(%#x)", self.hdc or 0)
        SwapBuffers(self.hdc)

    def update_geometry(self) -> None:
        """ not needed on MS Windows """

    def get_scale_factor(self) -> float:
        return 1

    def __repr__(self):
        return "WGLPaintContext(%#x)" % (self.context or 0)


class NullWidget:
    """
    Stand-in for the toolkit widget the shared `GLWindowBackingBase` expects as
    `self._backing`. The native win32 backend renders straight into the client
    window's `HWND`, so there is no real widget to show/realize/destroy.
    """

    def show(self) -> None:
        """ nothing to show: the window is managed natively """

    def hide(self) -> None:
        """ nothing to hide """

    def realize(self) -> None:
        """ nothing to realize """

    def destroy(self) -> None:
        """ nothing to destroy """

    def get_mapped(self) -> bool:
        return True


class GLWin32Backing(GLWindowBackingBase):
    """
    OpenGL window backing for the native win32 client.

    Binds a WGL context to the client window's own `HWND` (set via `set_hwnd`
    once the native window has been created) and presents the offscreen FBO by
    swapping the window's double buffer.
    """

    def __init__(self, wid: int, hwnd: HWND, width: int, height: int,
                 window_alpha: bool, pixel_depth: int = 0):
        self.hwnd: HWND = hwnd
        self.context: WGLContext | None = None
        self.window_context: WGLPaintContext | None = None
        super().__init__(wid, window_alpha, pixel_depth)
        # the FBO is created lazily (on the first `gl_init`), so we only need to
        # record the size here - no OpenGL context is required yet:
        self.render_size = (width, height)
        self.size = (width, height)

    def __repr__(self):
        return "GLWin32Backing(%#x, %s)" % (int(self.hwnd or 0), self.size)

    def set_hwnd(self, hwnd: HWND) -> None:
        # the native window is created after the backing (see the client window's
        # `create()`), so the real `HWND` is wired up here:
        log("set_hwnd(%#x)", hwnd or 0)
        self.hwnd = hwnd

    def init_gl_config(self) -> None:
        self.context = WGLContext(self._alpha_enabled)

    def init_backing(self) -> None:
        self._backing = NullWidget()

    def get_bit_depth(self, pixel_depth: int = 0) -> int:
        return pixel_depth or self.context.get_bit_depth() or 24

    def is_double_buffered(self) -> bool:
        return self.context.is_double_buffered()

    def get_backing_handle(self) -> int:
        return int(self.hwnd) or 0

    def gl_context(self) -> WGLPaintContext | None:
        if not self.hwnd:
            log("gl_context() no window handle yet")
            return None
        if not self.context.context:
            # (re)create the WGL context and bind it to our window's DC:
            self.context.create_wgl_context(self.hwnd)
        self.window_context = WGLPaintContext(self.context.hdc, self.context.context)
        return self.window_context

    def with_gl_context(self, cb: Callable, *args) -> None:
        gl_context = self.gl_context()
        if gl_context:
            with gl_context:
                cb(gl_context, *args)
        else:
            cb(None, *args)

    def do_gl_show(self, rect_count: int) -> None:
        if self.is_double_buffered():
            log("do_gl_show(%s) swapping buffers", rect_count)
            self.window_context.swap_buffers()

    def close_gl_config(self) -> None:
        if c := self.context:
            self.context = None
            c.destroy()

    def resize(self, width: int, height: int) -> None:
        # called from the client window's `WM_SIZE` handler:
        self.init(width, height, width, height)

    def paint(self, _hdc: HDC = 0) -> None:
        # called from the client window's `WM_PAINT` handler: re-present the FBO.
        # (the `hdc` from `BeginPaint` is unused - OpenGL swaps the whole window)
        self.gl_expose_rect(0, 0, *self.size)
