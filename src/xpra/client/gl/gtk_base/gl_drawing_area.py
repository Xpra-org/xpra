# This file is part of Xpra.
# Copyright (C) 2017 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys
from xpra.log import Logger
log = Logger("opengl", "paint")

from xpra.platform.gl_context import GLContext
if not GLContext:
    raise ImportError("no OpenGL context implementation for %s" % sys.platform)

from xpra.client.gl.gl_window_backing_base import GLWindowBackingBase
from xpra.gtk_common.gobject_compat import import_glib, import_gtk, gtk_version
from xpra.gtk_common.gtk_util import POINTER_MOTION_MASK, POINTER_MOTION_HINT_MASK
glib = import_glib()
gtk = import_gtk()


class GLDrawingArea(GLWindowBackingBase):

    def __repr__(self):
        return "gtk%i.GLDrawingArea(%s, %s, %s)" % (gtk_version(), self.wid, self.size, self.pixel_format)

    def idle_add(self, *args, **kwargs):
        glib.idle_add(*args, **kwargs)

    def init_gl_config(self, _window_alpha):
        self.context = GLContext()
        self.window_context = None

    def is_double_buffered(self):
        return self.context.is_double_buffered()

    def init_backing(self):
        da = gtk.DrawingArea()
        #da.connect('configure_event', self.on_configure_event)
        #da.connect('draw', self.on_draw)
        da.set_double_buffered(True)
        da.set_size_request(*self.size)
        da.set_events(da.get_events() | POINTER_MOTION_MASK | POINTER_MOTION_HINT_MASK)
        da.show()
        self._backing = da

    def get_bit_depth(self, pixel_depth):
        return self.context.get_bit_depth() or pixel_depth or 24

    def gl_context(self):
        b = self._backing
        if not b:
            return None
        gdk_window = b.get_window()
        assert gdk_window
        self.window_context = self.context.get_paint_context(gdk_window)
        return self.window_context

    def do_gl_show(self, _rect_count):
        if self.is_double_buffered():
            # Show the backbuffer on screen
            log("%s.gl_show() swapping buffers now", self)
            self.window_context.swap_buffers()
        else:
            #glFlush was enough
            pass

    def close(self):
        GLWindowBackingBase.close(self)
        c = self.context
        if c:
            self.context = None
            c.destroy()

    def cairo_draw(self, _context):
        w, h = self.size
        with self.gl_context():
            self.gl_init()
            self.present_fbo(0, 0, w, h)
