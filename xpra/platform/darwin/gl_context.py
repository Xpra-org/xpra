# This file is part of Xpra.
# Copyright (C) 2018 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from typing import Any

import objc
from Cocoa import (
    NSOpenGLContext, NSOpenGLPixelFormat, NSOpenGLPFAAccelerated,
    NSOpenGLPFAAlphaSize, NSOpenGLPFAColorSize,
    NSOpenGLPFADepthSize, NSOpenGLPFADoubleBuffer, NSOpenGLPFAAccumSize,
    NSOpenGLPFAStencilSize, NSOpenGLPFAAuxBuffers, NSOpenGLCPSurfaceOpacity,
    NSOpenGLGetVersion,
    NSOpenGLPFAOpenGLProfile, NSOpenGLProfileVersion3_2Core,
)
from xpra.gtk.window import GDKWindow
from xpra.opengl.check import check_PyOpenGL_support
from xpra.platform.darwin.gdk3_bindings import get_nsview_ptr, enable_transparency, get_backing_scale_factor
from xpra.util.env import envbool
from xpra.os_util import gi_import
from xpra.log import Logger

log = Logger("opengl")

# require hardware accelerated OpenGL:
ACCELERATED = envbool("XPRA_OPENGL_ACCELERATED", False)


class AGLWindowContext:

    def __init__(self, gl_context: NSOpenGLContext, nsview: int, gdk_window):
        self.gl_context = gl_context
        self.nsview = nsview
        self.gdk_window = gdk_window
        log("%s", self)
        self.gl_context.setView_(nsview)

    def __enter__(self):
        assert self.gl_context
        self.gl_context.makeCurrentContext()
        return self

    def __exit__(self, *_args):
        NSOpenGLContext.clearCurrentContext()

    def swap_buffers(self) -> None:
        assert self.gl_context
        self.gl_context.flushBuffer()

    def update_geometry(self) -> None:
        """
        The window has been resized,
        the gl context must be updated.
        """
        glc = self.gl_context
        log("update_geometry() gl_context=%s", glc)
        if glc:
            glc.update()

    def __del__(self):
        self.destroy()

    def get_scale_factor(self) -> float:
        return get_backing_scale_factor(self.gdk_window)

    def destroy(self) -> None:
        self.gl_context = None
        self.nsview = 0

    def __repr__(self):
        return f"AGLWindowContext({self.gl_context}, {self.nsview})"


class AGLContext:

    def __init__(self, alpha=True):
        self.alpha = alpha
        self.gl_context: NSOpenGLContext | None = None
        self.nsview_ptr: int = 0
        self.window_context: AGLWindowContext | None = None
        attrs = []
        if ACCELERATED:
            attrs.append(NSOpenGLPFAAccelerated)
        attrs += [
            NSOpenGLPFADoubleBuffer,
            NSOpenGLPFADepthSize, 24,
            NSOpenGLPFAOpenGLProfile, NSOpenGLProfileVersion3_2Core,
        ]
        if alpha:
            attrs += [
                NSOpenGLPFAAlphaSize,
                8,
            ]
        attrs.append(0)
        log(f"AGLContext({alpha}) creating NSOpenGLPixelFormat from {attrs}")
        self.pixel_format = NSOpenGLPixelFormat.alloc().initWithAttributes_(attrs)
        assert self.pixel_format is not None, "failed to initialize NSOpenGLPixelFormat with {}".format(attrs)
        c = NSOpenGLContext.alloc().initWithFormat_shareContext_(self.pixel_format, None)
        assert c is not None, "failed to initialize NSOpenGLContext with {}".format(self.pixel_format)
        self.gl_context = c

    def check_support(self, force_enable: bool = False) -> dict[str, Any]:
        # map our names (based on GTK's) to apple's constants:
        attr_name = {
            "rgba": (bool, NSOpenGLPFAAlphaSize),
            "depth": (int, NSOpenGLPFAColorSize),
            # "red-size"          : ?
            # "green-size"        : ?
            # "blue-size"         : ?
            # "red-shift"         : ?
            # "green-shift"       : ?
            # "blue-shift"        : ?
            # "alpha-shift"       : ?
            # "accum-red-size"    : ?
            # "accum-green-size"  : ?
            # "accum-blue-size"   : ?
            "alpha-size": (int, NSOpenGLPFAAlphaSize),
            "accum-size": (int, NSOpenGLPFAAccumSize),
            "depth-size": (int, NSOpenGLPFADepthSize),
            "stencil-size": (int, NSOpenGLPFAStencilSize),
            "aux-buffers": (int, NSOpenGLPFAAuxBuffers),
            # "visible-mask"      : ?
            "double-buffered": (int, NSOpenGLPFADoubleBuffer)
        }
        major, minor = NSOpenGLGetVersion(None, None)
        log(f"NSOpenGLGetVersion()={major},{minor}")
        nscreens = self.pixel_format.numberOfVirtualScreens()
        i = {
            # "pixel-format"      : self.pixel_format,
            "virtual-screens": nscreens,
        }
        for name, vdef in attr_name.items():
            conv, const_val = vdef  # ie (bool, NSOpenGLPFAAlphaSize)
            v = self._get_apfa(const_val)  # ie: NSOpenGLPFAAlphaSize=8
            i[name] = conv(v)  # ie: bool(8)
        # do it again but for each screen:
        if nscreens > 1:
            for screen in range(nscreens):
                si = i.setdefault("screen-%i" % screen, {})
                for name, vdef in attr_name.items():
                    conv, const_val = vdef  # ie (bool, NSOpenGLPFAAlphaSize)
                    v = self._get_pfa(const_val, screen)  # ie: NSOpenGLPFAAlphaSize=8
                    si[name] = conv(v)  # ie: bool(8)
        Gdk = gi_import("Gdk")
        tmp = GDKWindow(window_type=Gdk.WindowType.TEMP, title="tmp-opengl-check")
        with self.get_paint_context(tmp):
            i.update(check_PyOpenGL_support(force_enable))
        tmp.hide()
        return i

    def _get_pfa(self, attr, screen):
        return self.pixel_format.getValues_forAttribute_forVirtualScreen_(None, attr, screen)

    def _get_apfa(self, attr, fn=min):
        return fn(self._get_pfa(attr, screen) for screen in range(self.pixel_format.numberOfVirtualScreens()))

    def get_bit_depth(self) -> int:
        return int(self._get_apfa(NSOpenGLPFAColorSize))

    def is_double_buffered(self) -> bool:
        return bool(self._get_apfa(NSOpenGLPFADoubleBuffer))

    def get_paint_context(self, gdk_window) -> AGLWindowContext:
        if not self.gl_context:
            raise RuntimeError("no OpenGL context")
        nsview_ptr = get_nsview_ptr(gdk_window)
        if self.window_context and self.nsview_ptr != nsview_ptr:
            log("get_paint_context(%s) nsview_ptr has changed, was %#x, now %#x - destroying window context",
                gdk_window, nsview_ptr, self.nsview_ptr)
            self.window_context.destroy()
            self.window_context = None
        if not self.window_context:
            self.nsview_ptr = nsview_ptr
            nsview = objc.objc_object(c_void_p=nsview_ptr)
            log("get_paint_context(%s) nsview(%#x)=%s", gdk_window, nsview_ptr, nsview)
            if self.alpha and enable_transparency:
                self.gl_context.setValues_forParameter_([0], NSOpenGLCPSurfaceOpacity)
                enable_transparency(gdk_window)
            self.window_context = AGLWindowContext(self.gl_context, nsview, gdk_window)
        return self.window_context

    def __del__(self):
        self.destroy()

    def destroy(self) -> None:
        c = self.window_context
        log("AGLContext.destroy() window_context=%s", c)
        if c:
            self.window_context = None
            c.destroy()
        glc = self.gl_context
        if glc:
            self.gl_context = None
            glc.clearDrawable()
        self.pixel_format = None

    def __repr__(self):
        return "AGLContext(%#x)" % (self.nsview_ptr or 0)


GLContext = AGLContext
