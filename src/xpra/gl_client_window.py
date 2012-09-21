# This file is part of Parti.
# Copyright (C) 2012 Serviware (Arthur Huillet, <ahuillet@serviware.com>)
# Copyright (C) 2012 Antoine Martin <antoine@devloop.org.uk>
# Parti is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from wimpiggy.log import Logger
log = Logger()

from xpra.client_window import ClientWindow, queue_draw
from xpra.scripts.main import ENCODINGS


import gtk.gdkgl, gtk.gtkgl         #@UnresolvedImport
assert gtk.gdkgl is not None and gtk.gtkgl is not None

from OpenGL.GL import GL_VERSION, GL_PROJECTION, GL_MODELVIEW, GL_VERTEX_ARRAY, \
    GL_TEXTURE_COORD_ARRAY, GL_FRAGMENT_PROGRAM_ARB, \
    GL_PROGRAM_ERROR_STRING_ARB, GL_PROGRAM_FORMAT_ASCII_ARB, \
    GL_TEXTURE_RECTANGLE_ARB, GL_UNPACK_ROW_LENGTH, \
    GL_TEXTURE_MAG_FILTER, GL_TEXTURE_MIN_FILTER, GL_NEAREST, \
    GL_UNSIGNED_BYTE, GL_RGB, GL_LUMINANCE, GL_LINEAR, \
    GL_TEXTURE0, GL_TEXTURE1, GL_TEXTURE2, GL_QUADS, \
    glActiveTexture, \
    glGetString, glViewport, glMatrixMode, glLoadIdentity, glOrtho, \
    glEnableClientState, glDisable, glGenTextures, \
    glBindTexture, glPixelStorei, glEnable, glBegin, \
    glTexParameteri, glVertexPointeri, glTexCoordPointeri, \
    glTexImage2D, glTexSubImage2D, \
    glDrawArrays, glMultiTexCoord2i, \
    glVertex2i, glEnd
from OpenGL.GL.ARB.vertex_program import glGenProgramsARB, glBindProgramARB, glProgramStringARB
from OpenGL.GL.ARB.fragment_program import glInitFragmentProgramARB
from xpra.gl_colorspace_conversions import GL_COLORSPACE_CONVERSIONS

#sanity checks: OpenGL version
try:
    from gtk import gdk
    glconfig = gtk.gdkgl.Config(mode=gtk.gdkgl.MODE_RGB|gtk.gdkgl.MODE_SINGLE)
    glext = gtk.gdkgl.ext(gdk.Pixmap(gdk.get_default_root_window(), 1, 1))
    gldrawable = glext.set_gl_capability(glconfig)
    glcontext = gtk.gdkgl.Context(gldrawable, direct=True)
    if not gldrawable.gl_begin(glcontext):
        raise ImportError("gl_begin failed on %s" % gldrawable)
    try:
        gl_major = int(glGetString(GL_VERSION)[0])
        gl_minor = int(glGetString(GL_VERSION)[2])
        if gl_major<=1 and gl_minor<1:
            raise ImportError("** OpenGL output requires OpenGL version 1.1 or greater, not %s.%s" % (gl_major, gl_minor))
        log.info("found valid OpenGL: %s.%s", gl_major, gl_minor)

        #this allows us to do CSC via OpenGL:
        #see http://www.opengl.org/registry/specs/ARB/fragment_program.txt
        use_openGL_CSC = glInitFragmentProgramARB()
    finally:
        gldrawable.gl_end()
        del glcontext, gldrawable, glext, glconfig
except Exception, e:
    raise ImportError("** OpenGL initialization error: %s" % e)


class GLClientWindow(ClientWindow):
    MODE_UNINITIALIZED = 0
    MODE_RGB = 1
    MODE_YUV = 2

    def __init__(self, client, wid, x, y, w, h, metadata, override_redirect, client_properties, auto_refresh_delay):
        ClientWindow.__init__(self, client, wid, x, y, w, h, metadata, override_redirect, client_properties, auto_refresh_delay)
        display_mode = (gtk.gdkgl.MODE_RGB | gtk.gdkgl.MODE_SINGLE)
        self.glconfig = gtk.gdkgl.Config(mode=display_mode)
        self.glarea = gtk.gtkgl.DrawingArea(self.glconfig)
        self.glarea.set_size_request(w, h)
        self.glarea.show()
        self.add(self.glarea)
        self._video_decoder = None
        self._video_decoder_codec = None
        self.textures = None # OpenGL texture IDs
        self.current_mode = GLClientWindow.MODE_UNINITIALIZED

    def do_configure_event(self, event):
        ClientWindow.do_configure_event(self, event)
        drawable = self.glarea.get_gl_drawable()
        context = self.glarea.get_gl_context()

        self.yuv420_shader = None

        # Re-create textures
        self.current_mode = GLClientWindow.MODE_UNINITIALIZED

        if not drawable.gl_begin(context):
            raise Exception("** Cannot create OpenGL rendering context!")

        w, h = self.get_size()
        log("Configure widget size: %d x %d" % (w, h))
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

    def do_expose_event(self, event):
        log("do_expose_event(%s) area=%s", event, event.area)
        if not (self.flags() & gtk.MAPPED):
            return
        self.render_image()
        self.glarea.window.invalidate_rect(self.glarea.allocation, False)
        # Update window synchronously (fast).
        self.glarea.window.process_updates(False)

    def draw_region(self, x, y, width, height, coding, img_data, rowstride, options):
        #log("draw_region(%s, %s, %s, %s, %s, %s bytes, %s, %s)", x, y, width, height, coding, len(img_data), rowstride, options)
        if coding == "mmap":
            # No GL output for mmap
            assert coding != "mmap"
        elif coding == "rgb24":
            if rowstride>0:
                assert len(img_data) == rowstride * height
            else:
                assert len(img_data) == width * 3 * height
            self.update_texture_rgb24(img_data, x, y, width, height, rowstride)
        elif coding == "x264":
            assert "x264" in ENCODINGS
            from xpra.x264.codec import Decoder     #@UnresolvedImport
            self.paint_with_video_decoder(Decoder, "x264", img_data, x, y, width, height, rowstride, options)
        elif coding == "vpx":
            assert "vpx" in ENCODINGS
            from xpra.vpx.codec import Decoder     #@UnresolvedImport    @Reimport
            self.paint_with_video_decoder(Decoder, "vpx", img_data, x, y, width, height, rowstride, options)
        else:
            raise Exception("** No JPEG/PNG support for OpenGL")
        queue_draw(self, x, y, width, height)
        return  True

    #FIXME: This is a copypaste from window_backing.py...
    def paint_with_video_decoder(self, factory, coding, img_data, x, y, width, height, rowstride, options):
        assert x==0 and y==0
        if self._video_decoder:
            if self._video_decoder_codec!=coding:
                self._video_decoder.clean()
                self._video_decoder = None
            elif self._video_decoder.get_width()!=width or self._video_decoder.get_height()!=height:
                log("paint_with_video_decoder: window dimensions have changed from %s to %s", (self._video_decoder.get_width(), self._video_decoder.get_height()), (width, height))
                self._video_decoder.clean()
                self._video_decoder.init_context(width, height, options)
        if self._video_decoder is None:
            self._video_decoder = factory()
            self._video_decoder_codec = coding
            self._video_decoder.init_context(width, height, options)
        try:
            if use_openGL_CSC:
                decompress = self._video_decoder.decompress_image_to_yuv
                update_texture = self.update_texture_yuv420
            else:
                decompress = self._video_decoder.decompress_image_to_rgb
                update_texture = self.update_texture_rgb24

            err, outstride, data = decompress(img_data, options)
            if err!=0:
                log.error("paint_with_video_decoder: ouch, decompression error %s", err)
                return
            if not data:
                log.error("paint_with_video_decoder: ouch, no data from %s decoder", coding)
                return
            log("paint_with_video_decoder: decompressed %s to %s bytes (%s%%) of rgb24 (%s*%s*3=%s) (outstride: %s)", len(img_data), len(data), int(100*len(img_data)/len(data)),width, height, width*height*3, outstride)
            update_texture(data, x, y, width, height, outstride)
        finally:
            if not use_openGL_CSC:
                self._video_decoder.free_image()

    def update_texture_rgb24(self, img_data, x, y, width, height, rowstride):
        drawable = self.glarea.get_gl_drawable()
        context = self.glarea.get_gl_context()
        if not drawable.gl_begin(context):
            raise Exception("** Cannot create OpenGL rendering context!")
        assert self.textures is not None

        glBindTexture(GL_TEXTURE_RECTANGLE_ARB, self.textures[0])
        glPixelStorei(GL_UNPACK_ROW_LENGTH, rowstride/3)

        if self.current_mode == GLClientWindow.MODE_YUV:
            raise Exception("** YUV -> RGB mode change unimplemented!")
        elif self.current_mode == GLClientWindow.MODE_UNINITIALIZED:
            log("Creating new RGB texture")
            w, h = self.get_size()
            # First time we draw must be full image
            assert w == width and h == height
            glEnable(GL_TEXTURE_RECTANGLE_ARB)
            glTexParameteri(GL_TEXTURE_RECTANGLE_ARB, GL_TEXTURE_MAG_FILTER, GL_NEAREST);
            glTexParameteri(GL_TEXTURE_RECTANGLE_ARB, GL_TEXTURE_MIN_FILTER, GL_NEAREST);
            glTexImage2D(GL_TEXTURE_RECTANGLE_ARB, 0, GL_RGB, w, h, 0, GL_RGB, GL_UNSIGNED_BYTE, 0)
            self.current_mode = GLClientWindow.MODE_RGB
        log("Updating RGB texture")
        glTexSubImage2D(GL_TEXTURE_RECTANGLE_ARB, 0, x, y, width, height, GL_RGB, GL_UNSIGNED_BYTE, img_data)
        drawable.gl_end()
        self.render_image()

    def update_texture_yuv420(self, img_data, x, y, width, height, rowstrides):
        drawable = self.glarea.get_gl_drawable()
        context = self.glarea.get_gl_context()
        window_width, window_height = self.get_size()
        if not drawable.gl_begin(context):
            raise Exception("** Cannot create OpenGL rendering context!")
        assert self.textures is not None

        if self.current_mode == GLClientWindow.MODE_RGB:
            raise Exception("** RGB -> YUV mode change unimplemented!")
        elif self.current_mode == GLClientWindow.MODE_UNINITIALIZED:
            log("Creating new YUV textures")

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

            log("Assigning fragment program")
            glEnable(GL_FRAGMENT_PROGRAM_ARB)
            if not self.yuv420_shader:
                self.yuv420_shader = [ 1 ]
                glGenProgramsARB(1, self.yuv420_shader)
                glBindProgramARB(GL_FRAGMENT_PROGRAM_ARB, self.yuv420_shader[0])
                prog = GL_COLORSPACE_CONVERSIONS
                glProgramStringARB(GL_FRAGMENT_PROGRAM_ARB, GL_PROGRAM_FORMAT_ASCII_ARB, len(prog), prog)
                log.error(glGetString(GL_PROGRAM_ERROR_STRING_ARB))
                glBindProgramARB(GL_FRAGMENT_PROGRAM_ARB, self.yuv420_shader[0])

            self.current_mode = GLClientWindow.MODE_YUV

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
        self.render_image()

    def render_image(self):
        drawable = self.glarea.get_gl_drawable()
        context = self.glarea.get_gl_context()
        w, h = self.get_size()
        if not drawable.gl_begin(context):
            raise Exception("** Cannot create OpenGL rendering context!")
        texcoords = [ [ 0, 0 ],
                      [ 0, h ],
                      [ w, h ],
                      [ w, 0 ] ]
        vtxcoords = texcoords

        if self.current_mode == GLClientWindow.MODE_RGB:
            glVertexPointeri(vtxcoords)
            glTexCoordPointeri(texcoords)
            glDrawArrays(GL_QUADS, 0, 4);
        elif self.current_mode == GLClientWindow.MODE_YUV:
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

    def move_resize(self, x, y, w, h):
        assert self._override_redirect
        self.window.move_resize(x, y, w, h)

    def destroy(self):
        self._unfocus()
        self.glarea.destroy()
        gtk.Window.destroy(self)
        if self._video_decoder:
            self._video_decoder.clean()
            self._video_decoder = None
