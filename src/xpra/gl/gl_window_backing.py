# This file is part of Parti.
# Copyright (C) 2012, 2013 Antoine Martin <antoine@devloop.org.uk>
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

from xpra.codec_constants import YUV420P, YUV422P, YUV444P
from xpra.gl.gl_colorspace_conversions import GL_COLORSPACE_CONVERSIONS
from xpra.window_backing import PixmapBacking, fire_paint_callbacks
from OpenGL.GL import GL_PROJECTION, GL_MODELVIEW, GL_VERTEX_ARRAY, \
    GL_TEXTURE_COORD_ARRAY, GL_UNPACK_ROW_LENGTH, \
    GL_TEXTURE_MAG_FILTER, GL_TEXTURE_MIN_FILTER, GL_NEAREST, \
    GL_UNSIGNED_BYTE, GL_LUMINANCE, GL_LINEAR, \
    GL_TEXTURE0, GL_TEXTURE1, GL_TEXTURE2, GL_QUADS, \
    glActiveTexture, glTexSubImage2D, \
    glGetString, glViewport, glMatrixMode, glLoadIdentity, glOrtho, \
    glEnableClientState, glGenTextures, glDisable, \
    glBindTexture, glPixelStorei, glEnable, glBegin, glFlush, \
    glTexParameteri, \
    glTexImage2D, \
    glMultiTexCoord2i, \
    glVertex2i, glEnd
from OpenGL.GL.ARB.texture_rectangle import GL_TEXTURE_RECTANGLE_ARB
from OpenGL.GL.ARB.vertex_program import glGenProgramsARB, glDeleteProgramsARB, \
    glBindProgramARB, glProgramStringARB, GL_PROGRAM_ERROR_STRING_ARB, GL_PROGRAM_FORMAT_ASCII_ARB
from OpenGL.GL.ARB.fragment_program import GL_FRAGMENT_PROGRAM_ARB

"""
This is the gtk2 + OpenGL version.
"""
class GLPixmapBacking(PixmapBacking):
    RGB24 = 1   #make sure this never clashes with codec_constants!

    def __init__(self, wid, w, h, mmap_enabled, mmap):
        PixmapBacking.__init__(self, wid, w, h, mmap_enabled, mmap)
        display_mode = gtk.gdkgl.MODE_RGB | gtk.gdkgl.MODE_DEPTH | gtk.gdkgl.MODE_DOUBLE
        try:
            self.glconfig = gtk.gdkgl.Config(mode=display_mode)
        except gtk.gdkgl.NoMatches:
            display_mode &= ~gtk.gdkgl.MODE_DOUBLE
            self.glconfig = gtk.gdkgl.Config(mode=display_mode)
        self.glarea = gtk.gtkgl.DrawingArea(self.glconfig)
        self.glarea.show()
        self.glarea.connect("expose_event", self.gl_expose_event)
        self.textures = None # OpenGL texture IDs
        self.yuv_shader = None
        self.pixel_format = None
        self.size = 0, 0
        self.gl_setup = False
        self.paint_screen = False

    def init(self, w, h):
        #re-init gl context with new dimensions:
        self.gl_setup = False
        self.size = w, h
        # Re-create textures and shader
        self.pixel_format = None
        self.yuv_shader = None
        #also init the pixmap as backup:
        PixmapBacking.init(self, w, h)

    def gl_init(self):
        drawable = self.gl_begin()
        w, h = self.size
        log("GL Pixmap backing size: %d x %d, drawable=%s", w, h, drawable)
        if not drawable:
            return  None
        if not self.gl_setup:
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
            self.gl_setup = True
        return drawable

    def close(self):
        PixmapBacking.close(self)
        self.remove_shader()
        self.glarea = None
        self.glconfig = None

    def remove_shader(self):
        if self.yuv_shader:
            glDisable(GL_FRAGMENT_PROGRAM_ARB)
            glDeleteProgramsARB(1, self.yuv_shader)
            self.yuv_shader = None

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
        if drawable.is_double_buffered():
            drawable.swap_buffers()
        else:
            glFlush()
        drawable.gl_end()

    def gl_expose_event(self, glarea, event):
        log("gl_expose_event(%s, %s)", glarea, event)
        area = event.area
        x, y, w, h = area.x, area.y, area.width, area.height
        drawable = self.gl_init()
        log("gl_expose_event(%s, %s) drawable=%s", glarea, event, drawable)
        if drawable:
            try:
                self.render_image(x, y, w, h)
            finally:
                self.gl_end(drawable)

    def _do_paint_rgb24(self, img_data, x, y, width, height, rowstride, options, callbacks):
        gc = self._backing.new_gc()
        self.glarea.window.draw_rgb_image(gc, x, y, width, height, gdk.RGB_DITHER_NONE, img_data, rowstride)

    def do_video_paint(self, coding, img_data, x, y, w, h, options, callbacks):
        log("do_video_paint: options=%s, decoder=%s", options, type(self._video_decoder))
        err, rowstrides, img_data = self._video_decoder.decompress_image_to_yuv(img_data, options)
        csc_pixel_format = options.get("csc_pixel_format", -1)
        #this needs to be done here so we still hold the video_decoder lock:
        pixel_format = self._video_decoder.get_pixel_format(csc_pixel_format)
        success = err==0 and img_data and len(img_data)==3
        if not success:
            log.error("do_video_paint: %s decompression error %s on %s bytes of picture data for %sx%s pixels, options=%s",
                      coding, err, len(img_data), w, h, options)
            gobject.idle_add(fire_paint_callbacks, callbacks, False)
            return
        gobject.idle_add(self.do_gl_paint, x, y, w, h, img_data, rowstrides, pixel_format, callbacks)

    def do_gl_paint(self, x, y, w, h, img_data, rowstrides, pixel_format, callbacks):
        #this function runs in the UI thread, no video_decoder lock held
        drawable = self.gl_init()
        if not drawable:
            log("cannot paint, drawable is not set")
            fire_paint_callbacks(callbacks, False)
            return
        try:
            try:
                self.update_texture_yuv(img_data, x, y, w, h, rowstrides, pixel_format)
                if self.paint_screen:
                    self.render_image(x, y, x+w, y+h)
                fire_paint_callbacks(callbacks, True)
            except Exception, e:
                log.error("OpenGL paint error: %s", e, exc_info=True)
                fire_paint_callbacks(callbacks, False)
        finally:
            self.gl_end(drawable)


    def get_subsampling_divs(self, pixel_format):
        if pixel_format==YUV420P:
            return 1, 2, 2
        elif pixel_format==YUV422P:
            return 1, 2, 1
        elif pixel_format==YUV444P:
            return 1, 1, 1
        raise Exception("invalid pixel format: %s" % pixel_format)

    def update_texture_yuv(self, img_data, x, y, width, height, rowstrides, pixel_format):
        window_width, window_height = self.size
        assert self.textures is not None, "no OpenGL textures!"

        if self.pixel_format is None or self.pixel_format!=pixel_format:
            self.pixel_format = pixel_format
            divs = self.get_subsampling_divs(pixel_format)
            log("GL creating new YUV textures for pixel format %s using divs=%s", pixel_format, divs)
            # Create textures of the same size as the window's
            glEnable(GL_TEXTURE_RECTANGLE_ARB)

            for texture, index in ((GL_TEXTURE0, 0), (GL_TEXTURE1, 1), (GL_TEXTURE2, 2)):
                div = divs[index]
                glActiveTexture(texture)
                glBindTexture(GL_TEXTURE_RECTANGLE_ARB, self.textures[index])
                glEnable(GL_TEXTURE_RECTANGLE_ARB)
                mag_filter = GL_NEAREST
                if div>1:
                    mag_filter = GL_LINEAR
                glTexParameteri(GL_TEXTURE_RECTANGLE_ARB, GL_TEXTURE_MAG_FILTER, mag_filter)
                glTexParameteri(GL_TEXTURE_RECTANGLE_ARB, GL_TEXTURE_MIN_FILTER, GL_NEAREST)
                glTexImage2D(GL_TEXTURE_RECTANGLE_ARB, 0, GL_LUMINANCE, window_width/div, window_height/div, 0, GL_LUMINANCE, GL_UNSIGNED_BYTE, 0)

            log("Assigning fragment program")
            glEnable(GL_FRAGMENT_PROGRAM_ARB)
            if not self.yuv_shader:
                self.yuv_shader = [ 1 ]
                glGenProgramsARB(1, self.yuv_shader)
                glBindProgramARB(GL_FRAGMENT_PROGRAM_ARB, self.yuv_shader[0])
                prog = GL_COLORSPACE_CONVERSIONS
                glProgramStringARB(GL_FRAGMENT_PROGRAM_ARB, GL_PROGRAM_FORMAT_ASCII_ARB, len(prog), prog)
                err = glGetString(GL_PROGRAM_ERROR_STRING_ARB)
                if err:
                    #FIXME: maybe we should do something else here?
                    log.error(err)
                glBindProgramARB(GL_FRAGMENT_PROGRAM_ARB, self.yuv_shader[0])

        # Clamp width and height to the actual texture size
        if x + width > window_width:
            width = window_width - x
        if y + height > window_height:
            height = window_height - y

        divs = self.get_subsampling_divs(pixel_format)
        for texture, index in ((GL_TEXTURE0, 0), (GL_TEXTURE1, 1), (GL_TEXTURE2, 2)):
            div = divs[index]
            glActiveTexture(texture)
            glBindTexture(GL_TEXTURE_RECTANGLE_ARB, self.textures[index])
            glPixelStorei(GL_UNPACK_ROW_LENGTH, rowstrides[index])
            glTexSubImage2D(GL_TEXTURE_RECTANGLE_ARB, 0, x, y, width/div, height/div, GL_LUMINANCE, GL_UNSIGNED_BYTE, img_data[index])
        glFlush()

    def render_image(self, rx, ry, rw, rh):
        log("render_image %sx%s at %sx%s pixel_format=%s", rw, rh, rx, ry, self.pixel_format)
        if self.pixel_format not in (YUV420P, YUV422P, YUV444P):
            #not ready to render yet
            return
        divs = self.get_subsampling_divs(self.pixel_format)
        glEnable(GL_FRAGMENT_PROGRAM_ARB)
        glBegin(GL_QUADS)
        for x,y in ((rx, ry), (rx, ry+rh), (rx+rw, ry+rh), (rx+rw, ry)):
            for texture, index in ((GL_TEXTURE0, 0), (GL_TEXTURE1, 1), (GL_TEXTURE2, 2)):
                div = divs[index]
                glMultiTexCoord2i(texture, x/div, y/div)
            glVertex2i(x, y)
        glEnd()
        glFlush()
