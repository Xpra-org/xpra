# This file is part of Xpra.
# Copyright (C) 2012, 2013 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

#only works with gtk2:
import pygtk
pygtk.require('2.0')
import gtk.gtkgl
import gtk.gdkgl
assert gtk.gdkgl is not None and gtk.gtkgl is not None

from xpra.log import Logger
log = Logger()

from OpenGL.GL import GL_PROJECTION, GL_MODELVIEW, GL_RGB, \
    GL_TEXTURE_MAG_FILTER, GL_TEXTURE_MIN_FILTER, GL_NEAREST, \
    GL_UNSIGNED_BYTE,  GL_UNPACK_ALIGNMENT, \
    glViewport, glMatrixMode, glLoadIdentity, glOrtho, \
    glGenTextures, \
    glBindTexture, glPixelStorei, glEnable, glFlush, \
    glTexParameterf, \
    glTexImage2D
from OpenGL.GL.ARB.texture_rectangle import GL_TEXTURE_RECTANGLE_ARB

"""
Test version so we can try to make it work on win32..
"""
class GLTestBacking(object):

    def __init__(self, wid, w, h):
        display_mode = (
            gtk.gdkgl.MODE_RGB |
            gtk.gdkgl.MODE_DEPTH |
            gtk.gdkgl.MODE_DOUBLE
            )
        try:
            self.glconfig = gtk.gdkgl.Config(mode=display_mode)
        except gtk.gdkgl.NoMatches:
            display_mode &= ~gtk.gdkgl.MODE_DOUBLE
            self.glconfig = gtk.gdkgl.Config(mode=display_mode)
        self.glarea = gtk.gtkgl.DrawingArea(self.glconfig)
        self.glarea.connect("expose_event", self.gl_expose_event)
        self.glarea.connect_after('realize', self._on_realize)
        self.glarea.connect('configure_event', self._on_configure_event)
        self.texture_id = None
        self.glarea.set_size_request(w, h)
        self.size = w, h
        self.glarea.show()

    def init(self, w, h):
        self.size = w, h

    def close(self):
        self.glarea = None
        self.glconfig = None

    def gl_begin(self):
        if self.glarea is None:
            return None     #closed already
        drawable = self.glarea.get_gl_drawable()
        context = self.glarea.get_gl_context()
        if drawable is None or context is None:
            log.error("OpenGL error: no drawable or context!")
            return None
        if not drawable.gl_begin(context):
            log.error("OpenGL error: cannot create rendering context!")
            return None
        return drawable

    def gl_end(self, drawable):
        if False:
            glFlush()
        drawable.gl_end()

    def _on_configure_event(self, *args):
        log.info("_on_configure_event(%s) size=%s", args, self.size)
        drawable = self.gl_begin()
        assert drawable
        w, h = self.size
        glViewport(0, 0, w, h)
        self._set_view()
        if self.texture_id is None:
            self.config_texture()
        self.gl_end(drawable)

    def config_texture(self):
        w, h = self.size
        pixels = "\0" * w * h * 4

        # Create Texture
        print("glBindTexture(GL_TEXTURE_RECTANGLE_ARB) size=%s" % str(self.size))
        self.texture_id = glGenTextures(1)
        glBindTexture(GL_TEXTURE_RECTANGLE_ARB, self.texture_id)
        print("done")

        glPixelStorei(GL_UNPACK_ALIGNMENT, 1)
        glTexImage2D(GL_TEXTURE_RECTANGLE_ARB, 0, GL_RGB, w, h, 0,
                     GL_RGB, GL_UNSIGNED_BYTE, pixels)
        glTexParameterf(GL_TEXTURE_RECTANGLE_ARB, GL_TEXTURE_MAG_FILTER, GL_NEAREST)
        glTexParameterf(GL_TEXTURE_RECTANGLE_ARB, GL_TEXTURE_MIN_FILTER, GL_NEAREST)

    def _on_realize(self, *args):
        log.info("_on_realize(%s)", args)
        drawable = self.gl_begin()
        assert drawable
        self._set_view()

        glEnable(GL_TEXTURE_RECTANGLE_ARB)
        self.gl_end(drawable)

    def _set_view(self):
        log.info("_set_view()")
        glMatrixMode(GL_PROJECTION)
        glLoadIdentity()
        w, h = self.size
        glOrtho(0.0, w, h, 0.0, -1.0, 1.0)
        glMatrixMode(GL_MODELVIEW)
        glLoadIdentity()

    def gl_expose_event(self, glarea, event):
        log.info("gl_expose_event(%s, %s)", glarea, event)

    def do_gl_paint(self, x, y, w, h, img_data, rowstrides, pixel_format, callbacks):
        #pretend we did something
        pass
