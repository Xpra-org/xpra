# This file is part of Xpra.
# Copyright (C) 2013 Serviware (Arthur Huillet, <ahuillet@serviware.com>)
# Copyright (C) 2012-2015 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.log import Logger
log = Logger("opengl", "paint")

from xpra.client.gl.gl_window_backing_base import GLWindowBackingBase
from gi.repository import GdkGLExt  #@UnresolvedImport


"""
This is the gtk3 GObject Introspection version.
"""
class GLPixmapBacking(GLWindowBackingBase):

    def init_backing(self):
        GLWindowBackingBase.init_backing(self)

    def __repr__(self):
        return "gtk3."+GLWindowBackingBase.__repr__(self)

    def get_gl_drawable(self):
        window = self._backing.get_window()
        #probably not the right place to be doing this!
        return GdkGLExt.Window.new(self.glconfig, window, 0)

    def cairo_draw(self, context):
        log("cairo_draw(%s)", context)
