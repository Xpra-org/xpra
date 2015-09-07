# This file is part of Xpra.
# Copyright (C) 2012 Serviware (Arthur Huillet, <ahuillet@serviware.com>)
# Copyright (C) 2012-2014 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.log import Logger
log = Logger("opengl", "window")

import gobject

from xpra.client.gtk2.gtk2_window_base import GTK2WindowBase
from xpra.client.gl.gtk2.gl_window_backing import GLPixmapBacking


class GLClientWindow(GTK2WindowBase):

    MAX_TEXTURE_SIZE = 16*1024

    def __init__(self, *args):
        log("GLClientWindow(..)")
        GTK2WindowBase.__init__(self, *args)
        self.add(self._backing._backing)

    def get_backing_class(self):
        return GLPixmapBacking

    def init_window(self, metadata):
        mww, mwh = self.max_window_size
        mts = GLClientWindow.MAX_TEXTURE_SIZE
        if mts<16*1024 and (mww==0 or mwh==0 or mts<mww or mts<mwh):
            log("overriding max_window_size=%ix%i with %ix%i", mww, mwh, mts, mts)
            self.max_window_size = mts, mts
        GTK2WindowBase.init_window(self, metadata)

    def setup_window(self, *args):
        self._client_properties["encoding.uses_swscale"] = False
        GTK2WindowBase.setup_window(self, *args)


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
            b.gl_expose_event(self._backing._backing, "spinner: fake event")
            w, h = self.get_size()
            self.queue_draw(0, 0, w, h)

    def do_expose_event(self, event):
        log("GL do_expose_event(%s)", event)

    def do_configure_event(self, event):
        log("GL do_configure_event(%s)", event)
        GTK2WindowBase.do_configure_event(self, event)
        self._backing.paint_screen = True

    def destroy(self):
        self._backing.paint_screen = False
        GTK2WindowBase.destroy(self)

    def magic_key(self, *args):
        if self.border:
            self.border.shown = (not self.border.shown)
            self.queue_draw(0, 0, *self._size)

gobject.type_register(GLClientWindow)
