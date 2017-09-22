# This file is part of Xpra.
# Copyright (C) 2012 Serviware (Arthur Huillet, <ahuillet@serviware.com>)
# Copyright (C) 2012-2017 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.log import Logger
log = Logger("opengl", "window")

from collections import namedtuple
from xpra.client.gtk2.gtk2_window_base import GTK2WindowBase
from xpra.client.gl.gtk_base.gl_client_window_common import GLClientWindowCommon

Rectangle = namedtuple("Rectangle", "x,y,width,height")
DrawEvent = namedtuple("DrawEvent", "area")


class GLClientWindowBase(GLClientWindowCommon, GTK2WindowBase):

    def set_alpha(self):
        GTK2WindowBase.set_alpha(self)
        rgb_formats = self._client_properties.get("encodings.rgb_formats", [])
        GLClientWindowCommon.add_rgb_formats(self, rgb_formats)

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

    def new_backing(self, bw, bh):
        self.remove_backing()
        widget = GTK2WindowBase.new_backing(self, bw, bh)
        log("new_backing(%s, %s)=%s", bw, bh, widget)
        self.add(widget)

    def freeze(self):
        self.remove_backing()
        GTK2WindowBase.freeze(self)
