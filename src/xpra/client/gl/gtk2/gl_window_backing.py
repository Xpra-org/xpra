# This file is part of Xpra.
# Copyright (C) 2013 Serviware (Arthur Huillet, <ahuillet@serviware.com>)
# Copyright (C) 2012-2019 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from gtk import gtkgl         #@UnresolvedImport

from xpra.client.gl.gtk_base.gtkgl_window_backing_base import GTKGLWindowBackingBase

assert gtkgl


"""
This is the gtk2 pygtkglext version.
"""
class GLPixmapBacking(GTKGLWindowBackingBase):

    def init_backing(self):
        GTKGLWindowBackingBase.init_backing(self)
        self._backing.connect("expose_event", self.gl_expose_event)

    def __repr__(self):
        return "gtk2."+GTKGLWindowBackingBase.__repr__(self)

    def get_gl_drawable(self):
        return gtkgl.widget_get_gl_drawable(self._backing)

    def gl_expose_event(self, _glarea=None, event=None):
        if not self.paint_screen:
            return
        rect = None
        if event and event.area:
            area = event.area
            rect = (area.x, area.y, area.width, area.height)
        self.gl_expose_rect(rect)
