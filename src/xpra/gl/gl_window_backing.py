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
import os

from wimpiggy.log import Logger
log = Logger()
debug = log.debug
if os.environ.get("XPRA_OPENGL_DEBUG", "0")=="1":
    debug = log.info

from xpra.gl.gl_check import get_DISPLAY_MODE
from xpra.codec_constants import YUV420P, YUV422P, YUV444P, get_subsampling_divs
from xpra.gl.gl_colorspace_conversions import GL_COLORSPACE_CONVERSIONS
from xpra.window_backing import PixmapBacking, fire_paint_callbacks
from OpenGL.GL import GL_PROJECTION, GL_MODELVIEW, GL_VERTEX_ARRAY, \
    GL_TEXTURE_COORD_ARRAY, GL_UNPACK_ROW_LENGTH, GL_UNPACK_ALIGNMENT, \
    GL_TEXTURE_MAG_FILTER, GL_TEXTURE_MIN_FILTER, GL_NEAREST, \
    GL_UNSIGNED_BYTE, GL_LUMINANCE, GL_RGB, GL_LINEAR, \
    GL_TEXTURE0, GL_TEXTURE1, GL_TEXTURE2, GL_QUADS, GL_COLOR_BUFFER_BIT, \
    GL_FRONT, GL_FRONT_AND_BACK, GL_BACK, \
    glActiveTexture, glTexSubImage2D, \
    glGetString, glViewport, glMatrixMode, glLoadIdentity, glOrtho, \
    glEnableClientState, glGenTextures, glDisable, \
    glBindTexture, glPixelStorei, glEnable, glBegin, glFlush, \
    glTexParameteri, \
    glTexImage2D, \
    glMultiTexCoord2i, glColor3f, \
    glTexCoord2i, glVertex2i, glEnd, \
    glClear, glClearColor, glDrawBuffer, glReadBuffer, \
    glCopyTexImage2D
from OpenGL.GL.ARB.texture_rectangle import GL_TEXTURE_RECTANGLE_ARB
from OpenGL.GL.ARB.vertex_program import glGenProgramsARB, glDeleteProgramsARB, \
    glBindProgramARB, glProgramStringARB, GL_PROGRAM_ERROR_STRING_ARB, GL_PROGRAM_FORMAT_ASCII_ARB
from OpenGL.GL.ARB.fragment_program import GL_FRAGMENT_PROGRAM_ARB

"""
This is the gtk2 + OpenGL version.
"""
class GLPixmapBacking(PixmapBacking):

    def __init__(self, wid, w, h, mmap_enabled, mmap):
        PixmapBacking.__init__(self, wid, w, h, mmap_enabled, mmap)
        display_mode = get_DISPLAY_MODE()
        try:
            self.glconfig = gtk.gdkgl.Config(mode=display_mode)
        except gtk.gdkgl.NoMatches:
            display_mode &= ~gtk.gdkgl.MODE_DOUBLE
            self.glconfig = gtk.gdkgl.Config(mode=display_mode)
        self.glarea = gtk.gtkgl.DrawingArea(self.glconfig)
        #restoring missed masks:
        self.glarea.set_events(self.glarea.get_events() | gdk.POINTER_MOTION_MASK | gdk.POINTER_MOTION_HINT_MASK)
        self.glarea.show()
        self.glarea.connect("expose_event", self.gl_expose_event)
        self.textures = None # OpenGL texture IDs
        self.yuv_shader = None
        self.pixel_format = None
        self.size = 0, 0
        self.texture_size = 0, 0
        self.gl_setup = False
        self.paint_screen = False
        self._video_use_swscale = False
        self.draw_needs_refresh = False

    def init(self, w, h):
        #re-init gl projection with new dimensions
        #(see gl_init)
        if self.size!=(w, h):
            self.gl_setup = False
            self.size = w, h

    def gl_init(self):
        drawable = self.gl_begin()
        w, h = self.size
        debug("GL Pixmap backing size: %d x %d, drawable=%s", w, h, drawable)
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
            glEnable(GL_FRAGMENT_PROGRAM_ARB)
            if self.textures is None:
                self.textures = glGenTextures(4)
                debug("textures for wid=%s of size %s : %s", self.wid, self.size, self.textures)
            glClearColor(1.0, 1.0, 1.0, 1.0)
            self.gl_setup = True
        return drawable

    def close(self):
        PixmapBacking.close(self)
        self.remove_shader()
        self.glarea = None
        self.glconfig = None

    def remove_shader(self):
        if self.yuv_shader:
            drawable = self.gl_init()
            if drawable:
                try:
                    glDisable(GL_FRAGMENT_PROGRAM_ARB)
                    glDeleteProgramsARB(1, self.yuv_shader)
                finally:
                    drawable.gl_end()
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

    def present_backbuffer(self, drawable):
        if drawable.is_double_buffered():
            debug("SWAPPING BUFFERS NOW")
            drawable.swap_buffers()
            # Clear the new backbuffer to illustrate that its contents are undefined
            glClear(GL_COLOR_BUFFER_BIT)
        else:
            glFlush()

    def gl_expose_event(self, glarea, event):
        drawable = self.gl_init()
        debug("gl_expose_event(%s, %s) drawable=%s", glarea, event, drawable)
        if drawable:
            area = event.area
            try:
                # Expose event must redraw the whole image with up-to-date contents.
                # We strive to maintain the backbuffer up-to-date with full frame YUV refreshes + partial RGB refreshes
                # therefore at this point our backbuffer has to be presented on screen, but its contents must also
                # be subsequently restored for further RGB partial updates or expose events
                w, h = self.size

                glDisable(GL_FRAGMENT_PROGRAM_ARB);
                for texture in (GL_TEXTURE1, GL_TEXTURE2):
                    glActiveTexture(texture)
                    glDisable(GL_TEXTURE_RECTANGLE_ARB)
                    glActiveTexture(GL_TEXTURE0);
                    glEnable(GL_TEXTURE_RECTANGLE_ARB)
                glReadBuffer(GL_BACK)

                # Copy backbuffer data into RGB texture
                glBindTexture(GL_TEXTURE_RECTANGLE_ARB, self.textures[3])
                glTexParameteri(GL_TEXTURE_RECTANGLE_ARB, GL_TEXTURE_MAG_FILTER, GL_NEAREST)
                glTexParameteri(GL_TEXTURE_RECTANGLE_ARB, GL_TEXTURE_MIN_FILTER, GL_NEAREST)
                glTexImage2D(GL_TEXTURE_RECTANGLE_ARB, 0, GL_RGB, w, h, 0, GL_RGB, GL_UNSIGNED_BYTE, 0)

                glCopyTexImage2D(GL_TEXTURE_RECTANGLE_ARB, 0, GL_RGB, 0, 0, w, h, 0)
                self.present_backbuffer(drawable)

                glDrawBuffer(GL_BACK)
				# Draw textured RGB quad at the right coordinates
                glBegin(GL_QUADS)
                glTexCoord2i(0, h)
                glVertex2i(0, 0)
                glTexCoord2i(0, 0)
                glVertex2i(0, h)
                glTexCoord2i(w, 0)
                glVertex2i(w, h)
                glTexCoord2i(w, h)
                glVertex2i(w, 0)
                glEnd()
                # Reset state
                glEnable(GL_FRAGMENT_PROGRAM_ARB)
            finally:
                drawable.gl_end()


    def _do_paint_rgb24(self, img_data, x, y, width, height, rowstride, options, callbacks):
        debug("_do_paint_rgb24(x=%d, y=%d, width=%d, height=%d rowstride=%d)", x, y, width, height, rowstride)
        drawable = self.gl_init()
        if not drawable:
            debug("OpenGL cannot paint rgb24, drawable is not set")
            return False

        # Paint the partial RGB frame update to both the frontbuffer and backbuffer
        # This enables us to avoid a swap, and therefore keep the backbuffer available with up-to-date content
        # which will be used for the potential expose_event calls
        glDrawBuffer(GL_FRONT_AND_BACK)

        # Set GL state for RGB24 painting:
        #    no fragment program
        #    only tex unit #0 active
        glDisable(GL_FRAGMENT_PROGRAM_ARB);
        for texture in (GL_TEXTURE1, GL_TEXTURE2):
            glActiveTexture(texture)
            glDisable(GL_TEXTURE_RECTANGLE_ARB)
        glActiveTexture(GL_TEXTURE0);
        glEnable(GL_TEXTURE_RECTANGLE_ARB)


        # Upload data as temporary RGB texture
		
        glBindTexture(GL_TEXTURE_RECTANGLE_ARB, self.textures[3])
        glPixelStorei(GL_UNPACK_ROW_LENGTH, rowstride/3)
        glPixelStorei(GL_UNPACK_ALIGNMENT, 1)
        glTexParameteri(GL_TEXTURE_RECTANGLE_ARB, GL_TEXTURE_MAG_FILTER, GL_NEAREST)
        glTexParameteri(GL_TEXTURE_RECTANGLE_ARB, GL_TEXTURE_MIN_FILTER, GL_NEAREST)
        glTexImage2D(GL_TEXTURE_RECTANGLE_ARB, 0, 4, width, height, 0, GL_RGB, GL_UNSIGNED_BYTE, img_data)

        # Draw textured RGB quad at the right coordinates
        glBegin(GL_QUADS)
        glTexCoord2i(0, 0)
        glVertex2i(x, y)
        glTexCoord2i(0, height)
        glVertex2i(x, y+height)
        glTexCoord2i(width, height)
        glVertex2i(x+width, y+height)
        glTexCoord2i(width, 0)
        glVertex2i(x+width, y)
        glEnd()

        # Reset state
        glEnable(GL_FRAGMENT_PROGRAM_ARB)
        glFlush()
        glDrawBuffer(GL_BACK)

        # Absolutely do NOT SWAP BUFFERS
        # The RGB data has been rendered on the front buffer directly, 
        # and we keep it in the backbuffer for further RGB updates or expose events

        drawable.gl_end()
        return True

    def do_video_paint(self, coding, img_data, x, y, w, h, options, callbacks):
        debug("do_video_paint: options=%s, decoder=%s", options, type(self._video_decoder))
        err, rowstrides, data = self._video_decoder.decompress_image_to_yuv(img_data, options)
        csc_pixel_format = options.get("csc_pixel_format", -1)
        #this needs to be done here so we still hold the video_decoder lock:
        pixel_format = self._video_decoder.get_pixel_format(csc_pixel_format)
        success = err==0 and data and len(data)==3
        if not success:
            log.error("do_video_paint: %s decompression error %s on %s bytes of compressed picture data for %sx%s pixels, options=%s",
                      coding, err, len(img_data), w, h, options)
            gobject.idle_add(fire_paint_callbacks, callbacks, False)
            return
        gobject.idle_add(self.do_gl_paint, x, y, w, h, data, rowstrides, pixel_format, callbacks)

    def do_gl_paint(self, x, y, w, h, img_data, rowstrides, pixel_format, callbacks):
        #this function runs in the UI thread, no video_decoder lock held
        drawable = self.gl_init()
        if not drawable:
            debug("OpenGL cannot paint yuv, drawable is not set")
            fire_paint_callbacks(callbacks, False)
            return
        try:
            try:
                self.update_texture_yuv(img_data, x, y, w, h, rowstrides, pixel_format)
                if self.paint_screen:
                    # Paint backbuffer
                    self.render_image(x, y, x+w, y+h)
                    # Present it
                    self.present_backbuffer(drawable)
                    # Re-paint the backbuffer so that future RGB updates maintain an up-to-date backbuffer
                    self.render_image(x, y, x+w, y+h)
                fire_paint_callbacks(callbacks, True)
            except Exception, e:
                log.error("OpenGL paint error: %s", e, exc_info=True)
                fire_paint_callbacks(callbacks, False)
        finally:
            drawable.gl_end()


    def update_texture_yuv(self, img_data, x, y, width, height, rowstrides, pixel_format):
        assert x==0 and y==0
        assert self.textures is not None, "no OpenGL textures!"

        if self.pixel_format is None or self.pixel_format!=pixel_format or self.texture_size!=(width, height):
            self.pixel_format = pixel_format
            self.texture_size = (width, height)
            divs = get_subsampling_divs(pixel_format)
            debug("GL creating new YUV textures for pixel format %s using divs=%s", pixel_format, divs)
            # Create textures of the same size as the window's
            glEnable(GL_TEXTURE_RECTANGLE_ARB)

            for texture, index in ((GL_TEXTURE0, 0), (GL_TEXTURE1, 1), (GL_TEXTURE2, 2)):
                (div_w, div_h) = divs[index]
                glActiveTexture(texture)
                glBindTexture(GL_TEXTURE_RECTANGLE_ARB, self.textures[index])
                glEnable(GL_TEXTURE_RECTANGLE_ARB)
                mag_filter = GL_NEAREST
                if div_w > 1 or div_h > 1:
                    mag_filter = GL_LINEAR
                glTexParameteri(GL_TEXTURE_RECTANGLE_ARB, GL_TEXTURE_MAG_FILTER, mag_filter)
                glTexParameteri(GL_TEXTURE_RECTANGLE_ARB, GL_TEXTURE_MIN_FILTER, GL_NEAREST)
                glTexImage2D(GL_TEXTURE_RECTANGLE_ARB, 0, GL_LUMINANCE, width/div_w, height/div_h, 0, GL_LUMINANCE, GL_UNSIGNED_BYTE, 0)

            debug("Assigning fragment program")
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

        divs = get_subsampling_divs(pixel_format)
        U_width = 0
        U_height = 0
        for texture, index in ((GL_TEXTURE0, 0), (GL_TEXTURE1, 1), (GL_TEXTURE2, 2)):
            (div_w, div_h) = divs[index]
            glActiveTexture(texture)
            glBindTexture(GL_TEXTURE_RECTANGLE_ARB, self.textures[index])
            glPixelStorei(GL_UNPACK_ROW_LENGTH, rowstrides[index])
            glTexSubImage2D(GL_TEXTURE_RECTANGLE_ARB, 0, x, y, width/div_w, height/div_h, GL_LUMINANCE, GL_UNSIGNED_BYTE, img_data[index])
            if index == 1:
                U_width = width/div_w
                U_height = height/div_h
            elif index == 2:
                if width/div_w != U_width:
                    log.error("Width of V plane is %d, differs from width of corresponding U plane (%d), pixel_format is %d", width/div_w, U_width, pixel_format)
                if height/div_h != U_height:
                    log.error("Height of V plane is %d, differs from height of corresponding U plane (%d)", height/div_h, U_height)

    def render_image(self, rx, ry, rw, rh):
        debug("render_image %sx%s at %sx%s pixel_format=%s", rw, rh, rx, ry, self.pixel_format)
        if self.pixel_format not in (YUV420P, YUV422P, YUV444P):
            #not ready to render yet
            return
        divs = get_subsampling_divs(self.pixel_format)
        glEnable(GL_FRAGMENT_PROGRAM_ARB)
        glBindProgramARB(GL_FRAGMENT_PROGRAM_ARB, self.yuv_shader[0])
        for texture, index in ((GL_TEXTURE0, 0), (GL_TEXTURE1, 1), (GL_TEXTURE2, 2)):
            glActiveTexture(texture)
            glBindTexture(GL_TEXTURE_RECTANGLE_ARB, self.textures[index])

        tw, th = self.texture_size
        debug("render_image texture_size=%s, size=%s", self.texture_size, self.size)
        glBegin(GL_QUADS)
        for x,y in ((rx, ry), (rx, ry+rh), (rx+rw, ry+rh), (rx+rw, ry)):
            ax = min(tw, x)
            ay = min(th, y)
            for texture, index in ((GL_TEXTURE0, 0), (GL_TEXTURE1, 1), (GL_TEXTURE2, 2)):
                (div_w, div_h) = divs[index]
                glMultiTexCoord2i(texture, ax/div_w, ay/div_h)
            glVertex2i(ax, ay)
        glEnd()
