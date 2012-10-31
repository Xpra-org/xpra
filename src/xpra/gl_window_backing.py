# This file is part of Parti.
# Copyright (C) 2012 Antoine Martin <antoine@devloop.org.uk>
# Parti is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

#only works with gtk2:
from gtk import gdk
assert gdk
import gtk.gdkgl, gtk.gtkgl         #@UnresolvedImport
assert gtk.gdkgl is not None and gtk.gtkgl is not None
import gobject

from wimpiggy.log import Logger
log = Logger()

from xpra.gl_colorspace_conversions import GL_COLORSPACE_CONVERSIONS
from xpra.window_backing import PixmapBacking
from OpenGL.GL import GL_PROJECTION, GL_MODELVIEW, GL_VERTEX_ARRAY, \
    GL_TEXTURE_COORD_ARRAY, GL_FRAGMENT_PROGRAM_ARB, \
    GL_PROGRAM_ERROR_STRING_ARB, GL_PROGRAM_FORMAT_ASCII_ARB, \
    GL_TEXTURE_RECTANGLE_ARB, GL_UNPACK_ROW_LENGTH, \
    GL_TEXTURE_MAG_FILTER, GL_TEXTURE_MIN_FILTER, GL_NEAREST, \
    GL_UNSIGNED_BYTE, GL_LUMINANCE, GL_LINEAR, \
    GL_TEXTURE0, GL_TEXTURE1, GL_TEXTURE2, GL_QUADS, \
    glActiveTexture, glTexSubImage2D, \
    glGetString, glViewport, glMatrixMode, glLoadIdentity, glOrtho, \
    glEnableClientState, glGenTextures, glDisable, \
    glBindTexture, glPixelStorei, glEnable, glBegin, \
    glTexParameteri, \
    glTexImage2D, \
    glMultiTexCoord2i, \
    glVertex2i, glEnd
from OpenGL.GL.ARB.vertex_program import glGenProgramsARB, glBindProgramARB, glProgramStringARB

"""
This is the gtk2 + OpenGL version.
"""
class GLPixmapBacking(PixmapBacking):
    MODE_UNINITIALIZED = 0
    MODE_YUV = 1

    def __init__(self, wid, w, h, mmap_enabled, mmap):
        PixmapBacking.__init__(self, wid, w, h, mmap_enabled, mmap)
        display_mode = (gtk.gdkgl.MODE_RGB | gtk.gdkgl.MODE_SINGLE)
        self.glconfig = gtk.gdkgl.Config(mode=display_mode)
        self.glarea = gtk.gtkgl.DrawingArea(self.glconfig)
        self.glarea.set_size_request(w, h)
        self.glarea.show()
        self.textures = None # OpenGL texture IDs
        self.yuv420_shader = None
        self.size = 0, 0
        self.current_mode = GLPixmapBacking.MODE_UNINITIALIZED

    def init(self, w, h):
        #also init the pixmap as backup:
        self.size = w, h
        PixmapBacking.init(self, w, h)
        drawable = self.glarea.get_gl_drawable()
        context = self.glarea.get_gl_context()

        self.yuv420_shader = None

        # Re-create textures
        self.current_mode = GLPixmapBacking.MODE_UNINITIALIZED

        if not drawable.gl_begin(context):
            raise Exception("** Cannot create OpenGL rendering context!")

        log.info("GL Pixmap backing size: %d x %d", w, h)
        glViewport(0, 0, w, h)
        glMatrixMode(GL_PROJECTION)
        glLoadIdentity()
        glOrtho(0.0, w, h, 0.0, -1.0, 1.0)
        glMatrixMode(GL_MODELVIEW)
        glEnableClientState(GL_VERTEX_ARRAY)
        glEnableClientState(GL_TEXTURE_COORD_ARRAY)
        glDisable(GL_FRAGMENT_PROGRAM_ARB)

        if self.textures is None:
            self.textures = glGenTextures(3)

        drawable.gl_end()

    def render(self):
        log.info("GL render")
        self.render_image()
        self.glarea.window.invalidate_rect(self.glarea.allocation, False)
        # Update window synchronously (fast).
        self.glarea.window.process_updates(False)

    def do_video_paint(self, coding, img_data, x, y, width, height, options, callbacks):
        log.info("do_video_paint: options=%s, decoder=%s", options, type(self._video_decoder))
        err, rowstrides, img_data = self._video_decoder.decompress_image_to_yuv(img_data, options)
        success = err==0 and img_data and len(img_data)==3
        if not success:
            log.error("do_video_paint: %s decompression error %s on %s bytes of picture data for %sx%s pixels, options=%s",
                      coding, err, len(img_data), width, height, options)
            self.fire_paint_callbacks(callbacks, False)
            return
        def do_paint():
            self.update_texture_yuv420(img_data, x, y, width, height, rowstrides)
            self.render_image()
            self.fire_paint_callbacks(callbacks, True)
        gobject.idle_add(do_paint)

    def update_texture_yuv420(self, img_data, x, y, width, height, rowstrides):
        drawable = self.glarea.get_gl_drawable()
        context = self.glarea.get_gl_context()
        window_width, window_height = self.size
        if not drawable.gl_begin(context):
            raise Exception("** Cannot create OpenGL rendering context!")
        assert self.textures is not None

        if self.current_mode == GLPixmapBacking.MODE_UNINITIALIZED:
            log.info("Creating new YUV textures")

            # Create textures of the same size as the window's
            glEnable(GL_TEXTURE_RECTANGLE_ARB)
            glActiveTexture(GL_TEXTURE0);
            glBindTexture(GL_TEXTURE_RECTANGLE_ARB, self.textures[0])
            glEnable(GL_TEXTURE_RECTANGLE_ARB)
            glTexParameteri(GL_TEXTURE_RECTANGLE_ARB, GL_TEXTURE_MAG_FILTER, GL_NEAREST);
            glTexParameteri(GL_TEXTURE_RECTANGLE_ARB, GL_TEXTURE_MIN_FILTER, GL_NEAREST);
            glTexImage2D(GL_TEXTURE_RECTANGLE_ARB, 0, GL_LUMINANCE, window_width, window_height, 0, GL_LUMINANCE, GL_UNSIGNED_BYTE, 0);

            glActiveTexture(GL_TEXTURE1);
            glBindTexture(GL_TEXTURE_RECTANGLE_ARB, self.textures[1])
            glEnable(GL_TEXTURE_RECTANGLE_ARB)
            glTexParameteri(GL_TEXTURE_RECTANGLE_ARB, GL_TEXTURE_MAG_FILTER, GL_LINEAR);
            glTexParameteri(GL_TEXTURE_RECTANGLE_ARB, GL_TEXTURE_MIN_FILTER, GL_NEAREST);
            glTexImage2D(GL_TEXTURE_RECTANGLE_ARB, 0, GL_LUMINANCE, window_width/2, window_height/2, 0, GL_LUMINANCE, GL_UNSIGNED_BYTE, 0);

            glActiveTexture(GL_TEXTURE2);
            glBindTexture(GL_TEXTURE_RECTANGLE_ARB, self.textures[2])
            glEnable(GL_TEXTURE_RECTANGLE_ARB)
            glTexParameteri(GL_TEXTURE_RECTANGLE_ARB, GL_TEXTURE_MAG_FILTER, GL_LINEAR);
            glTexParameteri(GL_TEXTURE_RECTANGLE_ARB, GL_TEXTURE_MIN_FILTER, GL_NEAREST);
            glTexImage2D(GL_TEXTURE_RECTANGLE_ARB, 0, GL_LUMINANCE, window_width/2, window_height/2, 0, GL_LUMINANCE, GL_UNSIGNED_BYTE, 0);

            log.info("Assigning fragment program")
            glEnable(GL_FRAGMENT_PROGRAM_ARB)
            if not self.yuv420_shader:
                self.yuv420_shader = [ 1 ]
                glGenProgramsARB(1, self.yuv420_shader)
                glBindProgramARB(GL_FRAGMENT_PROGRAM_ARB, self.yuv420_shader[0])
                prog = GL_COLORSPACE_CONVERSIONS
                glProgramStringARB(GL_FRAGMENT_PROGRAM_ARB, GL_PROGRAM_FORMAT_ASCII_ARB, len(prog), prog)
                log.error(glGetString(GL_PROGRAM_ERROR_STRING_ARB))
                glBindProgramARB(GL_FRAGMENT_PROGRAM_ARB, self.yuv420_shader[0])

            self.current_mode = GLPixmapBacking.MODE_YUV
        else:
            assert self.current_mode == GLPixmapBacking.MODE_YUV

        # Clamp width and height to the actual texture size
        if x + width > window_width:
            width = window_width - x
        if y + height > window_height:
            height = window_height - y

        glActiveTexture(GL_TEXTURE0);
        glBindTexture(GL_TEXTURE_RECTANGLE_ARB, self.textures[0])
        glPixelStorei(GL_UNPACK_ROW_LENGTH, rowstrides[0])
        glTexSubImage2D(GL_TEXTURE_RECTANGLE_ARB, 0, x, y, width, height, GL_LUMINANCE, GL_UNSIGNED_BYTE, img_data[0])

        glActiveTexture(GL_TEXTURE1);
        glBindTexture(GL_TEXTURE_RECTANGLE_ARB, self.textures[1])
        glPixelStorei(GL_UNPACK_ROW_LENGTH, rowstrides[1])
        glTexSubImage2D(GL_TEXTURE_RECTANGLE_ARB, 0, x, y, width/2, height/2, GL_LUMINANCE, GL_UNSIGNED_BYTE, img_data[1])

        glActiveTexture(GL_TEXTURE2);
        glBindTexture(GL_TEXTURE_RECTANGLE_ARB, self.textures[2])
        glPixelStorei(GL_UNPACK_ROW_LENGTH, rowstrides[2])
        glTexSubImage2D(GL_TEXTURE_RECTANGLE_ARB, 0, x, y, width/2, height/2, GL_LUMINANCE, GL_UNSIGNED_BYTE, img_data[2])

        drawable.gl_end()

    def render_image(self):
        drawable = self.glarea.get_gl_drawable()
        context = self.glarea.get_gl_context()
        log.info("render_image() size=%s, using %s and %s", self.size, drawable, context)
        w, h = self.size
        if not drawable.gl_begin(context):
            raise Exception("** Cannot create OpenGL rendering context!")
        assert self.current_mode == GLPixmapBacking.MODE_YUV
        glEnable(GL_FRAGMENT_PROGRAM_ARB)
        glBegin(GL_QUADS);
        glMultiTexCoord2i(GL_TEXTURE0, 0, 0);
        glMultiTexCoord2i(GL_TEXTURE1, 0, 0);
        glMultiTexCoord2i(GL_TEXTURE2, 0, 0);
        glVertex2i(0, 0);

        glMultiTexCoord2i(GL_TEXTURE0, 0, h);
        glMultiTexCoord2i(GL_TEXTURE1, 0, h/2);
        glMultiTexCoord2i(GL_TEXTURE2, 0, h/2);
        glVertex2i(0, h);

        glMultiTexCoord2i(GL_TEXTURE0, w, h);
        glMultiTexCoord2i(GL_TEXTURE1, w/2, h/2);
        glMultiTexCoord2i(GL_TEXTURE2, w/2, h/2);
        glVertex2i(w, h);

        glMultiTexCoord2i(GL_TEXTURE0, w, 0);
        glMultiTexCoord2i(GL_TEXTURE1, w/2, 0);
        glMultiTexCoord2i(GL_TEXTURE2, w/2, 0);
        glVertex2i(w, 0);
        glEnd()

        drawable.swap_buffers()
        drawable.gl_end()
