# This file is part of Xpra.
# Copyright (C) 2013 Serviware (Arthur Huillet, <ahuillet@serviware.com>)
# Copyright (C) 2012-2015 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from gtk import gdk
assert gdk
from gtk import gtkgl         #@UnresolvedImport
assert gtkgl is not None

from xpra.log import Logger
log = Logger("opengl", "paint")

from xpra.client.gl.gl_window_backing_base import GLWindowBackingBase


"""
This is the gtk2 pygtkglext version.
"""
class GLPixmapBacking(GLWindowBackingBase):

    def init_backing(self):
        GLWindowBackingBase.init_backing(self)
        self._backing.connect("expose_event", self.gl_expose_event)

    def __repr__(self):
        return "gtk2."+GLWindowBackingBase.__repr__(self)

    def get_gl_drawable(self):
        return gtkgl.widget_get_gl_drawable(self._backing)

    def gl_expose_event(self, glarea=None, event=None):
        if not self.paint_screen:
            return
        context = self.gl_context()
        if event and event.area:
            area = event.area
            rect = (area.x, area.y, area.width, area.height)
        else:
            w, h = self.size
            rect = (0, 0, w, h)
        log("%s.gl_expose_event(%s, %s) context=%s, area=%s", self, glarea, event, context, area)
        if not context:
            return
        with context:
            self.gl_init()
            self.present_fbo(*rect)
