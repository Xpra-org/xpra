# This file is part of Xpra.
# Copyright (C) 2017-2019 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from ctypes import sizeof, byref, FormatError

from xpra.client.gl.gl_check import check_PyOpenGL_support
from xpra.platform.win32.gui import get_window_handle
from xpra.platform.win32.constants import (
    CS_OWNDC, CS_HREDRAW, CS_VREDRAW, COLOR_WINDOW,
    WS_OVERLAPPED, WS_SYSMENU, CW_USEDEFAULT,
    )
from xpra.platform.win32.common import (
    GetDC, SwapBuffers, ChoosePixelFormat, DescribePixelFormat, SetPixelFormat,
    BeginPaint, EndPaint, DestroyWindow, UnregisterClassA,
    GetModuleHandleA, RegisterClassExA, CreateWindowExA, DefWindowProcA, WNDPROC, WNDCLASSEX
    )
from xpra.platform.win32.glwin32 import (
    wglCreateContext, wglMakeCurrent, wglDeleteContext,
    PIXELFORMATDESCRIPTOR, PFD_TYPE_RGBA, PFD_DRAW_TO_WINDOW, PFD_SUPPORT_OPENGL,
    PFD_DOUBLEBUFFER, PFD_DEPTH_DONTCARE, PFD_SUPPORT_COMPOSITION, PFD_MAIN_PLANE,
    PAINTSTRUCT,
    )
from xpra.log import Logger

log = Logger("opengl")

DOUBLE_BUFFERED = True


def DefWndProc(hwnd, msg, wParam, lParam):
    return DefWindowProcA(hwnd, msg, wParam, lParam)

class WGLWindowContext:

    def __init__(self, hwnd, hdc, context):
        self.hwnd = hwnd
        self.hdc = hdc
        self.context = context
        self.ps = None
        self.paint_hdc = None

    def __enter__(self):
        log("wglMakeCurrent(%#x, %#x)", self.hdc, self.context)
        r = wglMakeCurrent(self.hdc, self.context)
        if not r:
            raise Exception("wglMakeCurrent failed")
        self.ps = PAINTSTRUCT()
        self.paint_hdc = BeginPaint(self.hwnd, byref(self.ps))
        assert self.paint_hdc, "BeginPaint: no display device context"
        log("BeginPaint hdc=%#x", self.paint_hdc)
        return self

    def __exit__(self, *_args):
        assert self.context
        log("EndPaint")
        EndPaint(self.hwnd, byref(self.ps))
        wglMakeCurrent(0, 0)
        self.paint_hdc = None
        self.ps = None

    def update_geometry(self):
        pass

    def swap_buffers(self):
        assert self.paint_hdc
        log("swap_buffers: calling SwapBuffers(%#x)", self.paint_hdc)
        SwapBuffers(self.paint_hdc)

    def __repr__(self):
        return "WGLWindowContext(%#x)" % self.hwnd


class WGLContext:

    def __init__(self, alpha=True):
        self.alpha = alpha
        self.hwnd = 0
        self.hdc = 0
        self.context = 0
        self.pixel_format_props = {}

    def check_support(self, force_enable=False):
        #create a temporary window to query opengl attributes:
        hInst = GetModuleHandleA(0)
        log("check_support() GetModuleHandleW()=%#x", hInst or 0)
        classname = "Xpra Temporary Window for OpenGL"
        wndc = WNDCLASSEX()
        wndc.cbSize = sizeof(WNDCLASSEX)
        wndc.style = CS_OWNDC | CS_HREDRAW | CS_VREDRAW
        wndc.hInstance = hInst
        wndc.hBrush = COLOR_WINDOW
        wndc.lpszClassName = classname
        wndc.lpfnWndProc = WNDPROC(DefWndProc)
        reg_atom = RegisterClassExA(byref(wndc))
        log("check_support() RegisterClassExW()=%#x", reg_atom or 0)
        if not reg_atom:
            return {"info" : "disabled: failed to register window class, %s" % FormatError()}
        style = WS_OVERLAPPED | WS_SYSMENU
        window_name = "Xpra OpenGL Test"
        self.hwnd = CreateWindowExA(0, reg_atom, window_name, style,
            CW_USEDEFAULT, CW_USEDEFAULT, 0, 0,
            0, 0, hInst, None)
        log("check_support() CreateWindowExW()=%#x", self.hwnd or 0)
        if not self.hwnd:
            return {"info" : "disabled: failed to create temporary window, %s" % FormatError()}
        try:
            self.context = self.create_wgl_context(self.hwnd)
            with WGLWindowContext(self.hwnd, self.hdc, self.context):
                props = check_PyOpenGL_support(force_enable)
            props["display_mode"] = [["SINGLE","DOUBLE"][int(DOUBLE_BUFFERED)], ]     #, "ALPHA"]
            return props
        finally:
            hwnd = self.hwnd
            self.destroy()
            if hwnd:
                if not DestroyWindow(hwnd):
                    log.warn("Warning: failed to destroy temporary OpenGL test window")
            if not UnregisterClassA(classname, hInst):
                log.warn("Warning: failed to unregister class for OpenGL test window")

    def get_bit_depth(self):
        return 0

    def is_double_buffered(self):
        return DOUBLE_BUFFERED  #self.pixel_format_props.get("double-buffered", False)

    def get_paint_context(self, gdk_window):
        hwnd = get_window_handle(gdk_window)
        if self.hwnd!=hwnd:
            #(this shouldn't happen)
            #just make sure we don't keep using a context for a different handle:
            self.destroy()
        if not self.context:
            self.context = self.create_wgl_context(hwnd)
        return WGLWindowContext(hwnd, self.hdc, self.context)

    def create_wgl_context(self, hwnd):
        bpc = 8
        self.hwnd = hwnd
        self.pixel_format_props = {}
        self.hdc = GetDC(hwnd)
        log("create_wgl_context(%#x) hdc=%#x", hwnd, self.hdc)
        flags = PFD_DRAW_TO_WINDOW | PFD_SUPPORT_OPENGL | PFD_DEPTH_DONTCARE
        if self.alpha:
            flags |= PFD_SUPPORT_COMPOSITION
        if DOUBLE_BUFFERED:
            flags |= PFD_DOUBLEBUFFER
        pfd = PIXELFORMATDESCRIPTOR()
        pfd.nsize = sizeof(PIXELFORMATDESCRIPTOR)
        pfd.nVersion = 1
        pfd.dwFlags = flags
        pfd.iPixelType = PFD_TYPE_RGBA
        pfd.cColorBits = bpc*(3+int(self.alpha))
        pfd.cRedBits = bpc
        pfd.cRedShift = 0
        pfd.cGreenBits = bpc
        pfd.cGreenShift = 0
        pfd.cBlueBits = bpc
        pfd.cBlueShift = 0
        pfd.cAlphaBits = int(self.alpha)*8
        pfd.cAlphaShift = 0
        pfd.cAccumBits = 0
        pfd.cAccumRedBits = 0
        pfd.cAccumGreenBits = 0
        pfd.cAccumBlueBits = 0
        pfd.cAccumAlphaBits = 0
        pfd.cDepthBits = 24
        pfd.cStencilBits = 2
        pfd.cAuxBuffers = 0
        pfd.iLayerType = PFD_MAIN_PLANE #ignored
        pfd.bReserved = 0
        pfd.dwLayerMask = 0
        pfd.dwVisibleMask = 0
        pfd.dwDamageMask = 0
        pf = ChoosePixelFormat(self.hdc, byref(pfd))
        log("ChoosePixelFormat for window %#x and %i bpc: %#x", hwnd, bpc, pf)
        if not SetPixelFormat(self.hdc, pf, byref(pfd)):
            raise Exception("SetPixelFormat failed")
        if not DescribePixelFormat(self.hdc, pf, sizeof(PIXELFORMATDESCRIPTOR), byref(pfd)):
            raise Exception("DescribePixelFormat failed")
        self.pixel_format_props.update({
            "rgba"              : pfd.iPixelType==PFD_TYPE_RGBA,
            "depth"             : pfd.cColorBits,
            "red-size"          : pfd.cRedBits,
            "green-size"        : pfd.cGreenBits,
            "blue-size"         : pfd.cBlueBits,
            "alpha-size"        : pfd.cAlphaBits,
            "red-shift"         : pfd.cRedShift,
            "green-shift"       : pfd.cGreenShift,
            "blue-shift"        : pfd.cBlueShift,
            "alpha-shift"       : pfd.cAlphaShift,
            "accum-red-size"    : pfd.cAccumRedBits,
            "accum-green-size"  : pfd.cAccumGreenBits,
            "accum-blue-size"   : pfd.cAccumBlueBits,
            "accum-size"        : pfd.cAccumBits,
            "depth-size"        : pfd.cDepthBits,
            "stencil-size"      : pfd.cStencilBits,
            "aux-buffers"       : pfd.cAuxBuffers,
            "visible-mask"      : int(pfd.dwVisibleMask),
            "double-buffered"   : bool(pfd.dwFlags & PFD_DOUBLEBUFFER)
            })
        log("DescribePixelFormat: %s", self.pixel_format_props)
        context = wglCreateContext(self.hdc)
        assert context, "wglCreateContext failed"
        log("wglCreateContext(%#x)=%#x", self.hdc, context)
        return context

    def destroy(self):
        c = self.context
        if c:
            self.context = 0
            if not wglDeleteContext(c):
                raise Exception("wglDeleteContext failed for context %#x" % c)
        self.hwnd = 0

    def __repr__(self):
        return "WGLContext(%#x)" % self.context

GLContext = WGLContext
