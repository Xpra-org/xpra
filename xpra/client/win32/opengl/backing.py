# This file is part of Xpra.
# Copyright (C) 2025 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from ctypes import byref
from ctypes.wintypes import HWND, HDC
from collections.abc import Callable

from xpra.client.gui.window.backing import WindowBackingBase
from xpra.opengl.backing import GLWindowBackingBase
from xpra.platform.win32.common import SwapBuffers, InvalidateRect, RECT
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

    def make_current(self) -> bool:
        log("wglMakeCurrent(%#x, %#x)", self.hdc or 0, self.context or 0)
        return bool(self.hdc) and bool(self.context) and bool(wglMakeCurrent(self.hdc, self.context))

    @staticmethod
    def release() -> None:
        wglMakeCurrent(0, 0)

    def __enter__(self):
        if not self.make_current():
            raise RuntimeError("wglMakeCurrent failed")
        return self

    def __exit__(self, *_args):
        self.release()

    def swap_buffers(self) -> None:
        log("swap_buffers: SwapBuffers(%#x)", self.hdc or 0)
        SwapBuffers(self.hdc)

    def update_geometry(self) -> None:
        """ not needed on MS Windows """

    @staticmethod
    def get_scale_factor() -> float:
        return 1

    def __repr__(self):
        return "WGLPaintContext(%#x)" % (self.context or 0)


class NullWidget:
    """
    Stand-in for the toolkit widget the shared `GLWindowBackingBase` expects as
    `self._backing`. The native win32 backend renders straight into the client
    window's `HWND`, so there is no real widget to show/realize/destroy.
    """

    def __init__(self, backing):
        # weak-ish back reference, only used to invalidate the native window:
        self.backing = backing

    def show(self) -> None:
        """ nothing to show: the window is managed natively """

    def hide(self) -> None:
        """ nothing to hide """

    def realize(self) -> None:
        """ nothing to realize """

    def destroy(self) -> None:
        self.backing = None

    def queue_draw_area(self, x: int, y: int, w: int, h: int) -> None:
        # called by the shared backing after an FBO resize:
        # there is no widget to invalidate, so go straight to the native window
        # (`InvalidateRect` posts a `WM_PAINT`, which re-presents the FBO):
        backing = self.backing
        hwnd = backing.hwnd if backing else 0
        log("queue_draw_area%s InvalidateRect(%#x)", (x, y, w, h), hwnd or 0)
        if hwnd:
            rect = RECT()
            rect.left = x
            rect.top = y
            rect.right = x + w
            rect.bottom = y + h
            InvalidateRect(hwnd, byref(rect), False)

    @staticmethod
    def get_mapped() -> bool:
        return True

    def __repr__(self):
        return "NullWidget"


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
        if self.hwnd and self.hwnd != hwnd:
            # the WGL context is tied to the old window's device context,
            # it cannot be re-used with a different `HWND`:
            self.destroy_wgl_context()
        self.hwnd = hwnd

    def init_gl_config(self) -> None:
        self.context = WGLContext(self._alpha_enabled)

    def init_backing(self) -> None:
        self._backing = NullWidget(self)

    def get_bit_depth(self, pixel_depth: int = 0) -> int:
        context = self.context
        return pixel_depth or (context.get_bit_depth() if context else 0) or 24

    def is_double_buffered(self) -> bool:
        context = self.context
        return context.is_double_buffered() if context else False

    def get_backing_handle(self) -> int:
        return int(self.hwnd) or 0

    def gl_context(self) -> WGLPaintContext | None:
        context = self.context
        if not self.hwnd or not context:
            log("gl_context() no window handle yet")
            return None
        if not context.context:
            # (re)create the WGL context and bind it to our window's DC.
            # `create_wgl_context` only *returns* the new `HGLRC` (it sets `hwnd`
            # and `hdc` as a side effect), so it is up to us to store it -
            # otherwise every paint would leak a context and `wglMakeCurrent`
            # would be called with a NULL handle, unbinding the context instead:
            try:
                context.context = context.create_wgl_context(self.hwnd)
            except RuntimeError:
                log.error("Error creating the WGL context for window %#x", self.hwnd or 0, exc_info=True)
                return None
            self.window_context = None
        if not self.window_context:
            self.window_context = WGLPaintContext(context.hdc, context.context)
        return self.window_context

    def with_gl_context(self, cb: Callable, *args) -> None:
        gl_context = self.gl_context()
        if gl_context and not gl_context.make_current():
            # the window or the context is gone: drop it so the next paint
            # re-creates one, and let the callback deal with having no context
            log.warn("Warning: failed to make the WGL context current for window %#x", self.hwnd or 0)
            self.destroy_wgl_context()
            gl_context = None
        if not gl_context:
            cb(None, *args)
            return
        try:
            cb(gl_context, *args)
        finally:
            gl_context.release()

    def do_gl_show(self, rect_count: int) -> None:
        if self.is_double_buffered() and self.window_context:
            log("do_gl_show(%s) swapping buffers", rect_count)
            self.window_context.swap_buffers()

    def destroy_wgl_context(self) -> None:
        self.window_context = None
        if (context := self.context) and context.context:
            log("destroy_wgl_context() destroying %s", context)
            # `WGLContext.destroy` raises if `wglDeleteContext` fails,
            # this must never abort the teardown path it is called from:
            try:
                context.destroy()
            except RuntimeError as e:
                log("destroy_wgl_context()", exc_info=True)
                log.warn("Warning: failed to destroy the WGL context for window %#x", self.hwnd or 0)
                log.warn(" %s", e)

    def close(self) -> None:
        # only tear the GL resources down if we ever had a context to create them with,
        # otherwise `close_gl` would just fail on every GL call it makes:
        if self.context and self.context.context and self.hwnd:
            super().close()
        else:
            log("close() no GL context to free")
            self.close_gl_config()
            WindowBackingBase.close(self)
        self.hwnd = 0

    def close_gl_config(self) -> None:
        self.destroy_wgl_context()
        self.context = None

    def paint(self, _hdc: HDC = 0) -> None:
        # called from the client window's `WM_PAINT` handler: re-present the FBO.
        # (the `hdc` from `BeginPaint` is unused - OpenGL swaps the whole window)
        self.gl_expose_rect(0, 0, *self.size)
