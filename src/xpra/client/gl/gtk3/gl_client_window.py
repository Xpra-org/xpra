# This file is part of Xpra.
# Copyright (C) 2012 Serviware (Arthur Huillet, <ahuillet@serviware.com>)
# Copyright (C) 2012-2014 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.log import Logger
log = Logger("opengl", "window")

from xpra.client.gtk3.client_window import ClientWindow
from xpra.client.gl.gtk3.gl_window_backing import GLPixmapBacking


class GLClientWindow(ClientWindow):

    def __init__(self, *args):
        log("GLClientWindow(..)")
        ClientWindow.__init__(self, *args)


    def get_backing_class(self):
        return GLPixmapBacking


    def __str__(self):
        return "GLClientWindow(%s : %s)" % (self._id, self._backing)

    def is_GL(self):
        return True

    def set_alpha(self):
        ClientWindow.set_alpha(self)
        rgb_formats = self._client_properties.get("encodings.rgb_formats", [])
        #gl_window_backing supports BGR(A) too:
        if "RGBA" in rgb_formats:
            rgb_formats.append("BGRA")
        if "RGB" in rgb_formats:
            rgb_formats.append("BGR")
            #TODO: we could handle BGRX as BGRA too...
            #rgb_formats.append("BGRX")

    def spinner(self, ok):
        #TODO
        pass

    def do_expose_event(self, event):
        log("GL do_expose_event(%s)", event)

    def do_configure_event(self, event):
        log("GL do_configure_event(%s)", event)
        ClientWindow.do_configure_event(self, event)
        self._backing.paint_screen = True

    def destroy(self):
        b = self._backing
        if b:
            b.paint_screen = False
            b.close()
            self._backing = None
        ClientWindow.destroy(self)


    def new_backing(self, bw, bh):
        widget = ClientWindow.new_backing(self, bw, bh)
        self.add(widget)


    def freeze(self):
        b = self._backing
        if b:
            glarea = b._backing
            if glarea:
                self.remove(glarea)
            b.close()
            self._backing = None
        self.iconify()


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
            self.border.shown = (not self.border.shown)
            if b:
                b.present_fbo(0, 0, *self._size)
        log("magic_key%s border=%s, backing=%s", args, self.border, b)

#gobject.type_register(GLClientWindow)
