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

    MAX_TEXTURE_SIZE = 16*1024

    def __init__(self, *args):
        log("GLClientWindow(..)")
        ClientWindow.__init__(self, *args)
        self.add(self._backing._backing)

    def get_backing_class(self):
        return GLPixmapBacking

    def init_window(self, metadata):
        mww, mwh = self.max_window_size
        mts = GLClientWindow.MAX_TEXTURE_SIZE
        if mts<16*1024 and (mww==0 or mwh==0 or mts<mww or mts<mwh):
            log("overriding max_window_size=%ix%i with %ix%i", mww, mwh, mts, mts)
            self.max_window_size = mts, mts
        ClientWindow.init_window(self, metadata)


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
        self._backing.paint_screen = False
        ClientWindow.destroy(self)

    def magic_key(self, *args):
        if self.border:
            self.border.shown = (not self.border.shown)
            self.queue_draw(0, 0, *self._size)

#gobject.type_register(GLClientWindow)
