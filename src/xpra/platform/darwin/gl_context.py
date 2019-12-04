# This file is part of Xpra.
# Copyright (C) 2018-2019 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import objc #@UnresolvedImport
from Cocoa import (
    NSOpenGLContext, NSOpenGLPixelFormat, NSOpenGLPFAWindow,                #@UnresolvedImport
    NSOpenGLPFAAlphaSize, NSOpenGLPFABackingStore, NSOpenGLPFAColorSize,    #@UnresolvedImport
    NSOpenGLPFADepthSize, NSOpenGLPFADoubleBuffer, NSOpenGLPFAAccumSize,    #@UnresolvedImport
    NSOpenGLPFAStencilSize, NSOpenGLPFAAuxBuffers, NSOpenGLCPSurfaceOpacity, #@UnresolvedImport
    )

from xpra.gtk_common.gtk_util import make_temp_window
from xpra.gtk_common.gobject_compat import is_gtk3
from xpra.client.gl.gl_check import check_PyOpenGL_support
from xpra.log import Logger

log = Logger("opengl")

if is_gtk3():
    from xpra.platform.darwin.gdk3_bindings import (    #@UnresolvedImport
        get_nsview_ptr, enable_transparency,            #@UnresolvedImport
        )
else:
    enable_transparency = None
    def get_nsview_ptr(window):
        return window.nsview


class AGLWindowContext(object):

    def __init__(self, gl_context, nsview):
        self.gl_context = gl_context
        self.nsview = nsview
        log("%s", self)
        self.gl_context.setView_(nsview)

    def __enter__(self):
        assert self.gl_context
        self.gl_context.makeCurrentContext()
        return self

    def __exit__(self, *_args):
        NSOpenGLContext.clearCurrentContext()

    def swap_buffers(self):
        assert self.gl_context
        self.gl_context.flushBuffer()

    def update_geometry(self):
        glc = self.gl_context
        log.warn("update() gl_context=%s", glc)
        if glc:
            glc.update()

    def __del__(self):
        self.destroy()

    def destroy(self):
        self.gl_context = None
        self.nsview = 0

    def __repr__(self):
        return "AGLWindowContext(%s, %s)" % (self.gl_context, self.nsview)


class AGLContext(object):

    def __init__(self, alpha=True):
        self.alpha = alpha
        self.gl_context = None
        self.nsview_ptr = None
        self.window_context = None
        self.pixel_format = NSOpenGLPixelFormat.new()
        attrs = [
            NSOpenGLPFAWindow,
            NSOpenGLPFADoubleBuffer,
            NSOpenGLPFAAlphaSize, 8,
            NSOpenGLPFABackingStore,
            NSOpenGLPFAColorSize, 32,       #for high bit depth, we should switch to 64 and NSOpenGLPFAColorFloat
            NSOpenGLPFADepthSize, 24,
            ]
        self.pixel_format = self.pixel_format.initWithAttributes_(attrs)
        assert self.pixel_format is not None, "failed to initialize NSOpenGLPixelFormat with %s" % (attrs,)
        c = NSOpenGLContext.alloc()
        c = c.initWithFormat_shareContext_(self.pixel_format, None)
        assert c is not None, "failed to initialize NSOpenGLContext with %s" % (self.pixel_format,)
        self.gl_context = c

    def check_support(self, force_enable=False):
        #map our names (based on GTK's) to apple's constants:
        attr_name = {
            "rgba"              : (bool,    NSOpenGLPFAAlphaSize),
            "depth"             : (int,     NSOpenGLPFAColorSize),
            #"red-size"          : ?
            #"green-size"        : ?
            #"blue-size"         : ?
            #"red-shift"         : ?
            #"green-shift"       : ?
            #"blue-shift"        : ?
            #"alpha-shift"       : ?
            #"accum-red-size"    : ?
            #"accum-green-size"  : ?
            #"accum-blue-size"   : ?
            "alpha-size"        : (int,     NSOpenGLPFAAlphaSize),
            "accum-size"        : (int,     NSOpenGLPFAAccumSize),
            "depth-size"        : (int,     NSOpenGLPFADepthSize),
            "stencil-size"      : (int,     NSOpenGLPFAStencilSize),
            "aux-buffers"       : (int,     NSOpenGLPFAAuxBuffers),
            #"visible-mask"      : ?
            "double-buffered"   : (int,     NSOpenGLPFADoubleBuffer)
            }
        nscreens = self.pixel_format.numberOfVirtualScreens()
        i = {
            #"pixel-format"      : self.pixel_format,
            "virtual-screens"   : nscreens,
            }
        for name,vdef in attr_name.items():
            conv, const_val = vdef              #ie (bool, NSOpenGLPFAAlphaSize)
            v = self._get_apfa(const_val)       #ie: NSOpenGLPFAAlphaSize=8
            i[name] = conv(v)                   #ie: bool(8)
        #do it again but for each screen:
        if nscreens>1:
            for screen in range(nscreens):
                si = i.setdefault("screen-%i" % screen, {})
                for name,vdef in attr_name.items():
                    conv, const_val = vdef              #ie (bool, NSOpenGLPFAAlphaSize)
                    v = self._get_pfa(const_val, screen)#ie: NSOpenGLPFAAlphaSize=8
                    si[name] = conv(v)                   #ie: bool(8)
        tmp = make_temp_window("tmp-opengl-check")
        with self.get_paint_context(tmp):
            i.update(check_PyOpenGL_support(force_enable))
        tmp.destroy()
        return i

    def _get_pfa(self, attr, screen):
        return self.pixel_format.getValues_forAttribute_forVirtualScreen_(None, attr, screen)

    def _get_apfa(self, attr, fn=min):
        return fn(self._get_pfa(attr, screen) for screen in range(self.pixel_format.numberOfVirtualScreens()))

    def get_bit_depth(self):
        return self._get_apfa(NSOpenGLPFAColorSize)

    def is_double_buffered(self):
        return self._get_apfa(NSOpenGLPFADoubleBuffer)

    def get_paint_context(self, gdk_window):
        nsview_ptr = get_nsview_ptr(gdk_window)
        if self.window_context and self.nsview_ptr!=nsview_ptr:
            self.window_context.destroy()
            self.window_context = None
        if not self.window_context:
            self.nsview_ptr = nsview_ptr
            nsview = objc.objc_object(c_void_p=nsview_ptr)
            log("get_paint_context(%s) nsview(%#x)=%s", gdk_window, nsview_ptr, nsview)
            if self.alpha and enable_transparency:
                self.gl_context.setValues_forParameter_([0], NSOpenGLCPSurfaceOpacity)
                enable_transparency(gdk_window)
            self.window_context = AGLWindowContext(self.gl_context, nsview)
        return self.window_context

    def __del__(self):
        self.destroy()

    def destroy(self):
        c = self.window_context
        if c:
            self.window_context = None
            c.destroy()
        glc = self.gl_context
        if glc:
            self.gl_context = None
            glc.clearDrawable()
        self.pixel_format = None

    def __repr__(self):
        return "AGLContext(%s)" % self.pixel_format


GLContext = AGLContext
