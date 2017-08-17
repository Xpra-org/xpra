# This file is part of Xpra.
# Copyright (C) 2012 Serviware (Arthur Huillet, <ahuillet@serviware.com>)
# Copyright (C) 2012-2014 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.log import Logger
log = Logger("opengl", "window")

import gobject

from collections import namedtuple
from xpra.client.gtk2.gtk2_window_base import GTK2WindowBase
from xpra.client.gl.gtk2.gl_window_backing import GLPixmapBacking


Rectangle = namedtuple("Rectangle", "x,y,w,h")
DrawEvent = namedtuple("DrawEvent", "area")


class GLClientWindow(GTK2WindowBase):

    __gsignals__ = GTK2WindowBase.__common_gsignals__


    def get_backing_class(self):
        return GLPixmapBacking


    def __str__(self):
        return "GLClientWindow(%s : %s)" % (self._id, self._backing)

    def is_GL(self):
        return True

    def set_alpha(self):
        GTK2WindowBase.set_alpha(self)
        rgb_formats = self._client_properties.get("encodings.rgb_formats", [])
        #gl_window_backing supports BGR(A) too:
        if "RGBA" in rgb_formats:
            rgb_formats.append("BGRA")
        if "RGB" in rgb_formats:
            rgb_formats.append("BGR")
            #TODO: we could handle BGRX as BGRA too...
            #rgb_formats.append("BGRX")

    def spinner(self, ok):
        b = self._backing
        log("spinner(%s) opengl window %s: backing=%s", ok, self._id, b)
        if not b:
            return
        b.paint_spinner = self.can_have_spinner() and not ok
        log("spinner(%s) backing=%s, paint_screen=%s, paint_spinner=%s", ok, b._backing, b.paint_screen, b.paint_spinner)
        if b._backing and b.paint_screen:
            w, h = self.get_size()
            self.queue_draw(0, 0, w, h)

    def queue_draw(self, x, y, w, h):
        b = self._backing
        if not b:
            return
        if b._backing and b.paint_screen:
            event = DrawEvent(area=Rectangle(x=x, y=y, width=w, height=h))
            b.gl_expose_event(b._backing, event)

    def do_expose_event(self, event):
        log("GL do_expose_event(%s)", event)

    def process_map_event(self):
        log("GL process_map_event()")
        GTK2WindowBase.process_map_event(self)
        self._backing.paint_screen = True

    def do_configure_event(self, event):
        log("GL do_configure_event(%s)", event)
        GTK2WindowBase.do_configure_event(self, event)
        self._backing.paint_screen = True

    def destroy(self):
        self.remove_backing()
        GTK2WindowBase.destroy(self)

    def remove_backing(self):
        b = self._backing
        if b:
            self._backing = None
            b.paint_screen = False
            b.close()
            glarea = b._backing
            if glarea:
                try:
                    self.remove(glarea)
                except:
                    pass

    def new_backing(self, bw, bh):
        self.remove_backing()
        widget = GTK2WindowBase.new_backing(self, bw, bh)
        log("new_backing(%s, %s)=%s", bw, bh, widget)
        self.add(widget)


    def freeze(self):
        self.remove_backing()
        GTK2WindowBase.freeze(self)


    def toggle_debug(self, *args):
        b = self._backing
        if not b:
            return
        if b.paint_box_line_width>0:
            b.paint_box_line_width = 0
        else:
            b.paint_box_line_width = b.default_paint_box_line_width

    def magic_key(self, *args):
        b = self._backing
        if self.border:
            self.border.toggle()
            if b:
                b.present_fbo(0, 0, *self._size)
                self.queue_draw(0, 0, *self._size)
        log("magic_key%s border=%s, backing=%s", args, self.border, b)

gobject.type_register(GLClientWindow)
