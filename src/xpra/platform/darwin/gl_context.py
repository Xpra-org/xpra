# This file is part of Xpra.
# Copyright (C) 2018 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.log import Logger
log = Logger("opengl")

import objc #@UnresolvedImport
from Cocoa import NSOpenGLContext, NSOpenGLPixelFormat, NSOpenGLPFAWindow, NSOpenGLPFAAlphaSize #@UnresolvedImport

from xpra.gtk_common.gtk_util import make_temp_window
from xpra.platform.darwin.gdk3_bindings import get_nsview_ptr   #@UnresolvedImport
from xpra.client.gl.gl_check import check_PyOpenGL_support


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
        self.nsview_ptr = None
        self.window_context = None
        self.pixel_format = NSOpenGLPixelFormat.new()
        attrs = [
            NSOpenGLPFAWindow,
            NSOpenGLPFAAlphaSize, 8,
            ]
        self.pixel_format = self.pixel_format.initWithAttributes_(attrs)
        assert self.pixel_format is not None, "failed to initialize NSOpenGLPixelFormat with %s" % (attrs,)
        c = NSOpenGLContext.alloc()
        c = c.initWithFormat_shareContext_(self.pixel_format, None)
        assert c is not None, "failed to initialize NSOpenGLContext with %s" % (self.pixel_format,)
        self.gl_context = c

    def check_support(self, force_enable=False):
        i = {
            #"pixel-format"      : self.pixel_format,
            "virtual-screens"   : self.pixel_format.numberOfVirtualScreens(),
            }
        tmp = make_temp_window("tmp-opengl-check")
        with self.get_paint_context(tmp):
            i.update(check_PyOpenGL_support(force_enable))
        tmp.destroy()
        return i

    def get_bit_depth(self):
        return 0

    def is_double_buffered(self):
        return True

    def get_paint_context(self, gdk_window):
        nsview_ptr = get_nsview_ptr(gdk_window)
        if self.window_context and self.nsview_ptr!=nsview_ptr:
            self.window_context.destroy()
            self.window_context = None
        if not self.window_context:
            self.nsview_ptr = nsview_ptr
            nsview = objc.objc_object(c_void_p=nsview_ptr)
            log("get_paint_context(%s) nsview(%#x)=%s", gdk_window, nsview_ptr, nsview)
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
