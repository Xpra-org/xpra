# This file is part of Xpra.
# Copyright (C) 2012 Serviware (Arthur Huillet, <ahuillet@serviware.com>)
# Copyright (C) 2012-2017 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.client.gtk3.gtk3_client_window import GTK3ClientWindow
from xpra.client.gl.gtk_base.gl_client_window_common import GLClientWindowCommon
from xpra.log import Logger

log = Logger("opengl", "window")


class GLClientWindowBase(GLClientWindowCommon, GTK3ClientWindow):

    def set_alpha(self):
        GTK3ClientWindow.set_alpha(self)
        rgb_formats = self._client_properties.get("encodings.rgb_formats", [])
        GLClientWindowCommon.add_rgb_formats(self, rgb_formats)

    def do_configure_event(self, event):
        log("GL do_configure_event(%s)", event)
        GTK3ClientWindow.do_configure_event(self, event)
        self._backing.paint_screen = True

    def destroy(self):
        self.remove_backing()
        GTK3ClientWindow.destroy(self)

    def new_backing(self, bw, bh):
        widget = GTK3ClientWindow.new_backing(self, bw, bh)
        if self.drawing_area:
            self.remove(self.drawing_area)
        self.init_widget_events(widget)
        self.add(widget)
        self.drawing_area = widget
        #maybe redundant?:
        self.apply_geometry_hints(self.geometry_hints)
