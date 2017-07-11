#!/usr/bin/env python
# Copyright (C) 2017 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import pygtk
pygtk.require('2.0')
import gtk
from gtk import gtkgl
from gtk import gdkgl

from OpenGL.GL import glClear, glBegin, glEnd, glClearColor, glViewport, \
    glShadeModel, glColor3f, glVertex2f, glFlush, GL_SMOOTH, GL_COLOR_BUFFER_BIT, GL_QUADS


SIZE = 1600, 1200

class GLContext(object):
    def __init__(self, widget):
        self.widget = widget
    def __enter__(self):
        self.glcontext = self.widget.get_gl_context()
        self.gldrawable = self.widget.get_gl_drawable()
        assert self.gldrawable.gl_begin(self.glcontext)
        return self.gldrawable
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.gldrawable.gl_end()


class ColorTest(object):

    def __init__(self):
        display_mode = gdkgl.MODE_RGBA | gdkgl.MODE_DOUBLE
        try:
            self.glconfig = gdkgl.Config(mode=display_mode)
        except gdkgl.NoMatches:
            self.display_mode &= ~gdkgl.MODE_DOUBLE
            self.glconfig = gdkgl.Config(mode=display_mode)

        win = gtk.Window()
        win.set_title('color test')
        win.connect('destroy', gtk.main_quit)

        glarea = gtkgl.DrawingArea(glconfig=self.glconfig, render_type=gdkgl.RGBA_TYPE)
        glarea.set_size_request(*SIZE)
        glarea.connect_after('realize', self.on_realize)
        glarea.connect('configure_event', self.on_configure_event)
        glarea.connect('expose_event', self.on_expose_event)
        self.glarea = glarea
        win.add(glarea)
        win.show_all()

    def on_realize(self, widget):
        with GLContext(widget):
            glClearColor(0.0, 0.0, 0.0, 0.0)

    def on_configure_event(self, widget, event):
        with GLContext(widget):
            glViewport(0, 0, widget.allocation.width, widget.allocation.height)
        return True

    def on_expose_event(self, widget, event=None):
        with GLContext(widget) as gldrawable:
            glClear(GL_COLOR_BUFFER_BIT)
            glShadeModel(GL_SMOOTH)
            glBegin(GL_QUADS)
            glColor3f(0.0,0.2,0.0); glVertex2f(-1.0, -1.0)
            glColor3f(0.0,0.2,0.0); glVertex2f(-1.0, 1.0)
            glColor3f(0.0,0.4,0.0); glVertex2f(1.0, 1.0)
            glColor3f(0.0,0.4,0.0); glVertex2f(1.0, -1.0)
            glEnd();

            if gldrawable.is_double_buffered():
                gldrawable.swap_buffers()
            else:
                glFlush()
        return True


if __name__ == '__main__':
    ColorTest()
    gtk.main()
