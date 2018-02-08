# This file is part of Xpra.
# Copyright (C) 2018 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.log import Logger
log = Logger("opengl")

import objc #@UnresolvedImport
from Cocoa import NSOpenGLContext, NSOpenGLPixelFormat, NSOpenGLPFAWindow, NSOpenGLPFAAlphaSize #@UnresolvedImport

from xpra.platform.darwin.gdk3_bindings import get_nsview_ptr   #@UnresolvedImport


class AGLWindowContext(object):

    def __init__(self, window):
        w, h = window.get_geometry()[2:4]
        self.nsview = get_nsview_ptr(window)
        log("AGLWindowContext(%s) size=%ix%i, nsview=%#x", window, w, h, self.nsview)
        p = NSOpenGLPixelFormat.new()
        attrs = [
            NSOpenGLPFAWindow,
            NSOpenGLPFAAlphaSize, 8,
            ]
        p = p.initWithAttributes_(attrs)
        assert p is not None, "failed to initialize NSOpenGLPixelFormat with %s" % (attrs,)
        c = NSOpenGLContext.alloc()
        c = c.initWithFormat_shareContext_(p, None)
        assert c is not None, "failed to initialize NSOpenGLContext with %s" % (p,)
        self.context = c
        view = objc.objc_object(c_void_p=self.nsview)
        c.setView_(view)

    def __enter__(self):
        assert self.context
        self.context.makeCurrentContext()
        return self

    def __exit__(self, *_args):
        NSOpenGLContext.clearCurrentContext()

    def swap_buffers(self):
        assert self.context
        self.context.flushBuffer()

    def __del__(self):
        self.destroy()

    def destroy(self):
        c = self.context
        if c:
            self.context = None

    def __repr__(self):
        return "AGLWindowContext(%#x)" % self.nsview


class AGLContext(object):

    def __init__(self, alpha=True):
        self.alpha = alpha
        self.window = None
        self.context = None

    def check_support(self, force_enable=False):
        return {}

    def get_bit_depth(self):
        return 0

    def is_double_buffered(self):
        return True

    def get_paint_context(self, gdk_window):
        if self.window!=gdk_window or not self.context:
            self.destroy()
            self.window = gdk_window
            self.context = AGLWindowContext(gdk_window)
        return self.context

    def destroy(self):
        c = self.context
        if c:
            self.context = None
            c.destroy()

    def __repr__(self):
        return "AGLContext(%#x)" % self.nsview


GLContext = AGLContext
