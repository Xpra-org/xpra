# This file is part of Xpra.
# Copyright (C) 2012 Serviware (Arthur Huillet, <ahuillet@serviware.com>)
# Copyright (C) 2012-2017 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.log import Logger
log = Logger("opengl", "window")

from xpra.client.gtk3.client_window import ClientWindow
from xpra.client.gl.gtk_base.gl_client_window_common import GLClientWindowCommon


class GLClientWindowBase(GLClientWindowCommon, ClientWindow):

    def set_alpha(self):
        ClientWindow.set_alpha(self)
        rgb_formats = self._client_properties.get("encodings.rgb_formats", [])
        GLClientWindowCommon.add_rgb_formats(self, rgb_formats)

    def do_configure_event(self, event):
        log("GL do_configure_event(%s)", event)
        ClientWindow.do_configure_event(self, event)
        self._backing.paint_screen = True

    def destroy(self):
        self.remove_backing()
        ClientWindow.destroy(self)

    def new_backing(self, bw, bh):
        widget = ClientWindow.new_backing(self, bw, bh)
        self.add(widget)
