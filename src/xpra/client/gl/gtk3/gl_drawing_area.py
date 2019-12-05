# This file is part of Xpra.
# Copyright (C) 2017 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys
from gi.repository import GLib, Gtk, Gdk

from xpra.client.gl.gl_window_backing_base import GLWindowBackingBase
from xpra.platform.gl_context import GLContext
from xpra.log import Logger

if not GLContext:
    raise ImportError("no OpenGL context implementation for %s" % sys.platform)

log = Logger("opengl", "paint")


class GLDrawingArea(GLWindowBackingBase):

    def __repr__(self):
        return "GLDrawingArea(%s, %s, %s)" % (self.wid, self.size, self.pixel_format)

    def idle_add(self, *args, **kwargs):
        GLib.idle_add(*args, **kwargs)

    def init_gl_config(self):
        self.context = GLContext(self._alpha_enabled)  #pylint: disable=not-callable
        self.window_context = None

    def is_double_buffered(self):
        return self.context.is_double_buffered()

    def init_backing(self):
        da = Gtk.DrawingArea()
        #da.connect('configure_event', self.on_configure_event)
        #da.connect('draw', self.on_draw)
        #double-buffering is enabled by default anyway, so this is redundant:
        #da.set_double_buffered(True)
        da.set_size_request(*self.size)
        da.set_events(da.get_events() | Gdk.EventMask.POINTER_MOTION_MASK | Gdk.EventMask.POINTER_MOTION_HINT_MASK)
        da.show()
        self._backing = da

    def get_bit_depth(self, pixel_depth=0):
        return self.context.get_bit_depth() or pixel_depth or 24

    def gl_context(self):
        b = self._backing
        if not b:
            return None
        gdk_window = b.get_window()
        assert gdk_window
        self.window_context = self.context.get_paint_context(gdk_window)
        return self.window_context

    def do_gl_show(self, rect_count):
        if self.is_double_buffered():
            # Show the backbuffer on screen
            log("%s.do_gl_show(%s) swapping buffers now", rect_count, self)
            self.window_context.swap_buffers()
        else:
            #glFlush was enough
            pass

    def close_gl_config(self):
        c = self.context
        if c:
            self.context = None
            c.destroy()

    def draw_fbo(self, _context):
        w, h = self.size
        with self.gl_context():
            self.gl_init()
            self.present_fbo(0, 0, w, h)
