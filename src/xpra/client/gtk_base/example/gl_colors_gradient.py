#!/usr/bin/env python
# Copyright (C) 2017-2020 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.platform import program_context
from xpra.gtk_common.gtk_util import add_close_accel

from OpenGL.GL import (
    glClear, glClearColor, glViewport,
    glColor3f, glFlush, glRectf, GL_COLOR_BUFFER_BIT,
    )

import gi
gi.require_version("Gtk", "3.0")
gi.require_version("Pango", "1.0")
from gi.repository import Gtk, Pango



SIZE = 1600, 1200

class GLContext:
    def __init__(self, widget):
        self.widget = widget
    def __enter__(self):
        self.glcontext = self.widget.get_gl_context()
        self.gldrawable = self.widget.get_gl_drawable()
        assert self.gldrawable.gl_begin(self.glcontext)
        return self.gldrawable
    def __exit__(self, *_args):
        self.gldrawable.gl_end()


class ColorTest:

    def __init__(self):
        #FIXME: needs porting to GTK3:
        display_mode = gdkgl.MODE_RGB | gdkgl.MODE_DOUBLE
        try:
            self.glconfig = gdkgl.Config(mode=display_mode)
        except gdkgl.NoMatches:
            display_mode &= ~gdkgl.MODE_DOUBLE
            self.glconfig = gdkgl.Config(mode=display_mode)

        win = Gtk.Window()
        win.set_title('OpenGL Color Gradient')
        win.connect('destroy', Gtk.main_quit)
        self.win = win

        vbox = Gtk.VBox()
        self.win.add(vbox)

        self.bpc = 16
        self.label = Gtk.Label(" ")
        self.label.modify_font(Pango.FontDescription("sans 24"))
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
        add_close_accel(win, Gtk.main_quit)

    def on_realize(self, widget):
        with GLContext(widget):
            glClearColor(0.0, 0.0, 0.0, 0.0)

    def populate_label(self):
        txt = "Clipped to %i bits per channel" % self.bpc
        self.label.set_text(txt)

    def on_key_press(self, _widget, key_event):
        if key_event.string == "-":
            self.bpc = ((self.bpc-2) % 16)+1
        else:
            self.bpc = (self.bpc%16)+1
        self.populate_label()
        self.win.queue_draw()
        self.on_expose_event(self.glarea, None)

    def on_configure_event(self, widget, _event):
        with GLContext(widget):
            glViewport(0, 0, widget.allocation.width, widget.allocation.height)
        return True

    def on_expose_event(self, widget, _event=None):
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
        for _ in range(16-self.bpc):
            mask = mask*2+1
        mask = 0xffff ^ mask
        def normv(v):
            assert 0<=v<=M
            iv = int(v) & mask
            return max(0, iv/M)
        def paint_block(R=M, G=M, B=M):
            y = 1.0-self.index/(blocks/2.0)
            bw = 2.0/w
            bh = 2.0/blocks
            self.index += 1
            for i in range(w):
                v = i/w
                r = normv(R*v)
                g = normv(G*v)
                b = normv(B*v)
                glColor3f(r, g, b)
                x = -1+float(i)/(w//2)
                glRectf(x, y, x+bw, y+bh)
        self.index = 1
        paint_block(M, 0, 0)
        paint_block(0, M-1, 0)
        paint_block(0, 0, M-2)
        paint_block(0, M-3, M-3)
        paint_block(M-4, 0, M-4)
        paint_block(M-5, M-5, 0)
        paint_block(0, 0, 0)
        #Black Shade Blocks:
        paint_block(M, M, M)
        paint_block(M//2, M//2, M//2)
        paint_block(M//4, M//4, M//4)
        paint_block(M//8, M//8, M//8)
        paint_block(M//16, M//16, M//16)

def main():
    with program_context("gl-colors-gradient", "OpenGL Colors Gradient"):
        import signal
        def signal_handler(*_args):
            Gtk.main_quit()
        signal.signal(signal.SIGINT, signal_handler)
        ColorTest()
        Gtk.main()


if __name__ == '__main__':
    main()
