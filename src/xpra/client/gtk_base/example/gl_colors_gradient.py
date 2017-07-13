#!/usr/bin/env python
# Copyright (C) 2017 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import pango
import pygtk
pygtk.require('2.0')
import gtk
from gtk import gtkgl
from gtk import gdkgl

from OpenGL.GL import glClear, glBegin, glEnd, glClearColor, glViewport, \
    glShadeModel, glColor3f, glVertex2f, glFlush, glRectf, GL_SMOOTH, GL_COLOR_BUFFER_BIT, GL_QUADS


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
        display_mode = gdkgl.MODE_RGB | gdkgl.MODE_DOUBLE
        try:
            self.glconfig = gdkgl.Config(mode=display_mode)
        except gdkgl.NoMatches:
            display_mode &= ~gdkgl.MODE_DOUBLE
            self.glconfig = gdkgl.Config(mode=display_mode)

        win = gtk.Window()
        win.set_title('OpenGL Color Gradient')
        win.connect('destroy', gtk.main_quit)
        self.win = win

        vbox = gtk.VBox()
        self.win.add(vbox)

        self.bpc = 16
        self.label = gtk.Label(" ")
        self.label.modify_font(pango.FontDescription("sans 24"))
        self.populate_label()
        vbox.add(self.label)

        glarea = gtkgl.DrawingArea(glconfig=self.glconfig, render_type=gdkgl.RGBA_TYPE)
        glarea.set_size_request(*SIZE)
        glarea.connect_after('realize', self.on_realize)
        glarea.connect('configure_event', self.on_configure_event)
        glarea.connect('expose_event', self.on_expose_event)
        win.connect("key_press_event", self.on_key_press)
        self.glarea = glarea
        vbox.add(glarea)
        win.show_all()

    def on_realize(self, widget):
        with GLContext(widget):
            glClearColor(0.0, 0.0, 0.0, 0.0)

    def populate_label(self):
        txt = "Clipped to %i bits per channel" % self.bpc
        self.label.set_text(txt)

    def on_key_press(self, *args):
        self.bpc = ((self.bpc-2) % 16)+1
        self.populate_label()
        self.win.queue_draw()
        self.on_expose_event(self.glarea, None)

    def on_configure_event(self, widget, event):
        with GLContext(widget):
            glViewport(0, 0, widget.allocation.width, widget.allocation.height)
        return True

    def on_expose_event(self, widget, event=None):
        with GLContext(widget) as gldrawable:
            self.paint_blocks()

            if gldrawable.is_double_buffered():
                gldrawable.swap_buffers()
            else:
                glFlush()
        return True


    def paint_blocks(self):
        glClear(GL_COLOR_BUFFER_BIT)
        w, _ = self.glarea.get_window().get_size()
        blocks = 12
        M = 2**16-1
        mask = 0
        for i in range(16-self.bpc):
            mask = mask*2+1
        mask = 0xffff ^ mask
        def normv(v):
            assert 0<=v<=M
            iv = int(v) & mask
            return max(0, float(iv)/M)
        def paint_block(R=M, G=M, B=M, label=""):
            y = 1.0-float(self.index)/(blocks/2.0)
            bw = 2.0/w
            bh = 2.0/blocks
            self.index += 1
            for i in range(w):
                v = float(i)/float(w)
                r = normv(R*v)
                g = normv(G*v)
                b = normv(B*v)

                glColor3f(r, g, b)
                x = -1+float(i)/(w//2)
                glRectf(x, y, x+bw, y+bh)

            #if label:
            #    cr.set_font_size(32)
            #    cr.set_source_rgb(1, 1, 1)
            #    cr.move_to(w//2-12, y+bh//2+8)
            #    cr.show_text(label)

        #txt = "Clipped to %i bits per channel" % self.bpc
        #cr.move_to(w//2-8*len(txt), bh//2+8)
        #cr.show_text(txt)

        self.index = 1
        paint_block(M, 0, 0, "R")
        paint_block(0, M-1, 0, "G")
        paint_block(0, 0, M-2, "B")
        paint_block(0, M-3, M-3, "C")
        paint_block(M-4, 0, M-4, "M")
        paint_block(M-5, M-5, 0, "Y")
        paint_block(0, 0, 0, "K")
        #Black Shade Blocks:
        paint_block(M, M, M)
        paint_block(M//2, M//2, M//2)
        paint_block(M//4, M//4, M//4)
        paint_block(M//8, M//8, M//8)
        paint_block(M//16, M//16, M//16)


if __name__ == '__main__':
    ColorTest()
    gtk.main()
