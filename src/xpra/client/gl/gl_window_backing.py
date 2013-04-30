# This file is part of Xpra.
# Copyright (C) 2013 Serviware (Arthur Huillet, <ahuillet@serviware.com>)
# Copyright (C) 2012, 2013 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

#only works with gtk2:
from gtk import gdk
assert gdk
import gtk.gdkgl, gtk.gtkgl         #@UnresolvedImport
assert gtk.gdkgl is not None and gtk.gtkgl is not None
import gobject

from xpra.log import Logger, debug_if_env
log = Logger()
debug = debug_if_env(log, "XPRA_OPENGL_DEBUG")

from xpra.codecs.codec_constants import YUV420P, YUV422P, YUV444P, get_subsampling_divs
from xpra.client.gl.gl_check import get_DISPLAY_MODE
from xpra.client.gl.gl_colorspace_conversions import GL_COLORSPACE_CONVERSIONS
from xpra.client.gtk2.window_backing import GTK2WindowBacking, fire_paint_callbacks
from OpenGL.GL import GL_PROJECTION, GL_MODELVIEW, \
    GL_UNPACK_ROW_LENGTH, GL_UNPACK_ALIGNMENT, \
    GL_TEXTURE_MAG_FILTER, GL_TEXTURE_MIN_FILTER, GL_NEAREST, \
    GL_UNSIGNED_BYTE, GL_LUMINANCE, GL_RGB, GL_LINEAR, \
    GL_TEXTURE0, GL_TEXTURE1, GL_TEXTURE2, GL_QUADS, GL_COLOR_BUFFER_BIT, \
    GL_DONT_CARE, GL_TRUE,\
    glActiveTexture, glTexSubImage2D, \
    glGetString, glViewport, glMatrixMode, glLoadIdentity, glOrtho, \
    glGenTextures, glDisable, \
    glBindTexture, glPixelStorei, glEnable, glBegin, glFlush, \
    glTexParameteri, \
    glTexImage2D, \
    glMultiTexCoord2i, \
    glTexCoord2i, glVertex2i, glEnd, \
    glClear, glClearColor
from OpenGL.GL.ARB.texture_rectangle import GL_TEXTURE_RECTANGLE_ARB
from OpenGL.GL.ARB.vertex_program import glGenProgramsARB, \
    glBindProgramARB, glProgramStringARB, GL_PROGRAM_ERROR_STRING_ARB, GL_PROGRAM_FORMAT_ASCII_ARB
from OpenGL.GL.ARB.fragment_program import GL_FRAGMENT_PROGRAM_ARB
from OpenGL.GL.ARB.framebuffer_object import GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, glGenFramebuffers, glBindFramebuffer, glFramebufferTexture2D
try:
    from OpenGL.GL.KHR.debug import GL_DEBUG_OUTPUT, GL_DEBUG_OUTPUT_SYNCHRONOUS, glDebugMessageControl, glDebugMessageCallback, glInitDebugKHR
except ImportError:
    log.warn("Unable to import GL_KHR_debug OpenGL extension. Debug output will be more limited.")
    GL_DEBUG_OUTPUT = None
try:
    from OpenGL.GL.GREMEDY.string_marker import glInitStringMarkerGREMEDY, glStringMarkerGREMEDY
    from OpenGL.GL.GREMEDY.frame_terminator import glInitFrameTerminatorGREMEDY, glFrameTerminatorGREMEDY
    from OpenGL.GL import GLDEBUGPROC #@UnresolvedImport
    def py_gl_debug_callback(source, error_type, error_id, severity, length, message, param):
        log.error("src %x type %x id %x severity %x length %d message %s", source, error_type, error_id, severity, length, message)
    gl_debug_callback = GLDEBUGPROC(py_gl_debug_callback)
except ImportError:
    # This is normal- GREMEDY_string_marker is only available with OpenGL debuggers
    gl_debug_callback = None
    glInitStringMarkerGREMEDY = None
    glStringMarkerGREMEDY = None
    glInitFrameTerminatorGREMEDY = None
    glFrameTerminatorGREMEDY = None
from ctypes import c_char_p


# Texture number assignment
#  1 = Y plane
#  2 = U plane
#  3 = V plane
#  4 = RGB updates
#  5 = FBO texture (guaranteed up-to-date window contents)
TEX_Y = 0
TEX_U = 1
TEX_V = 2
TEX_RGB = 3
TEX_FBO = 4

"""
This is the gtk2 + OpenGL version.
The logic is as follows:

We create an OpenGL framebuffer object, which will be always up-to-date with the latest windows contents.
This framebuffer object is updated with YUV painting and RGB painting. It is presented on screen by drawing a
textured quad when requested, that is: after each YUV or RGB painting operation, and upon receiving an expose event.
The use of a intermediate framebuffer object is the only way to guarantee that the client keeps an always fully up-to-date
window image, which is critical because of backbuffer content losses upon buffer swaps or offscreen window movement.
"""
class GLPixmapBacking(GTK2WindowBacking):

    def __init__(self, wid, w, h):
        GTK2WindowBacking.__init__(self, wid, w, h)
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
        self.offscreen_fbo = None

    def init(self, w, h):
        #re-init gl projection with new dimensions
        #(see gl_init)
        if self.size!=(w, h):
            self.gl_setup = False
            self.size = w, h

    def gl_marker(self, msg):
        if not bool(glStringMarkerGREMEDY):
            return
        c_string = c_char_p(msg)
        glStringMarkerGREMEDY(0, c_string)

    def gl_frame_terminator(self):
        # Mark the end of the frame
        # This makes the debug output more readable especially when doing single-buffered rendering
        if not bool(glFrameTerminatorGREMEDY):
            return
        glFrameTerminatorGREMEDY()

    def gl_init(self):
        drawable = self.gl_begin()
        w, h = self.size
        debug("GL Pixmap backing size: %d x %d, drawable=%s", w, h, drawable)
        if not drawable:
            return  None
        if not self.gl_setup:
            # Ask GL to send us all debug messages
            if GL_DEBUG_OUTPUT and gl_debug_callback and glInitDebugKHR() == True:
                glEnable(GL_DEBUG_OUTPUT)
                glEnable(GL_DEBUG_OUTPUT_SYNCHRONOUS)
                glDebugMessageCallback(gl_debug_callback, None)
                glDebugMessageControl(GL_DONT_CARE, GL_DONT_CARE, GL_DONT_CARE, 0, None, GL_TRUE)
            # Initialize string_marker GL debugging extension if available
            if glInitStringMarkerGREMEDY and glInitStringMarkerGREMEDY() == True:
                log.info("Extension GL_GREMEDY_string_marker available. Will output detailed information about each frame.")
            else:
                # General case - running without debugger, extension not available
                glStringMarkerGREMEDY = None
            # Initialize frame_terminator GL debugging extension if available
            if glInitFrameTerminatorGREMEDY and glInitFrameTerminatorGREMEDY() == True:
                glFrameTerminatorGREMEDY = None



            self.gl_marker("Initializing GL context for window size %d x %d" % (w, h))
            # Initialize viewport and matrices for 2D rendering
            glViewport(0, 0, w, h)
            glMatrixMode(GL_PROJECTION)
            glLoadIdentity()
            glOrtho(0.0, w, h, 0.0, -1.0, 1.0)
            glMatrixMode(GL_MODELVIEW)
            #TODO glEnableClientState(GL_VERTEX_ARRAY)
            #TODO glEnableClientState(GL_TEXTURE_COORD_ARRAY)

            # Clear to white
            glClearColor(1.0, 1.0, 1.0, 1.0)

            # Default state is good for YUV painting:
            #  - fragment program enabled
            #  - render to offscreen FBO
            glEnable(GL_FRAGMENT_PROGRAM_ARB)
            if self.textures is None:
                self.textures = glGenTextures(5)
                debug("textures for wid=%s of size %s : %s", self.wid, self.size, self.textures)
            if self.offscreen_fbo is None:
                self.offscreen_fbo = glGenFramebuffers(1)

            # Define empty FBO texture and set rendering to FBO
            glBindTexture(GL_TEXTURE_RECTANGLE_ARB, self.textures[TEX_FBO])
            glTexImage2D(GL_TEXTURE_RECTANGLE_ARB, 0, GL_RGB, w, h, 0, GL_RGB, GL_UNSIGNED_BYTE, 0)

            glBindFramebuffer(GL_FRAMEBUFFER, self.offscreen_fbo)
            glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_TEXTURE_RECTANGLE_ARB, self.textures[TEX_FBO], 0)
            glClear(GL_COLOR_BUFFER_BIT)

            self.gl_setup = True
        return drawable

    def close(self):
        GTK2WindowBacking.close(self)
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

    def set_rgb24_paint_state(self):
        # Set GL state for RGB24 painting:
        #    no fragment program
        #    only tex unit #0 active
        self.gl_marker("Switching to RGB24 paint state")
        glDisable(GL_FRAGMENT_PROGRAM_ARB);
        for texture in (GL_TEXTURE1, GL_TEXTURE2):
            glActiveTexture(texture)
            glDisable(GL_TEXTURE_RECTANGLE_ARB)
        glActiveTexture(GL_TEXTURE0);
        glEnable(GL_TEXTURE_RECTANGLE_ARB)

    def unset_rgb24_paint_state(self):
        # Reset state to our default
        self.gl_marker("Switching back to YUV paint state")
        glEnable(GL_FRAGMENT_PROGRAM_ARB)

    def present_fbo(self):
        drawable = self.gl_init()
        debug("present_fbo() drawable=%s", drawable)
        self.gl_marker("Presenting FBO on screen")
        if not drawable:
            return
        # Change state to target screen instead of our FBO
        glBindFramebuffer(GL_FRAMEBUFFER, 0)

        # Draw FBO texture on screen
        self.set_rgb24_paint_state()

        glBindTexture(GL_TEXTURE_RECTANGLE_ARB, self.textures[TEX_FBO])

        w, h = self.size
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

        # Show the backbuffer on screen
        if drawable.is_double_buffered():
            debug("SWAPPING BUFFERS NOW")
            drawable.swap_buffers()
            # Clear the new backbuffer to illustrate that its contents are undefined
            glClear(GL_COLOR_BUFFER_BIT)
        else:
            glFlush()
        self.gl_frame_terminator()

        self.unset_rgb24_paint_state()
        glBindFramebuffer(GL_FRAMEBUFFER, self.offscreen_fbo)
        drawable.gl_end()

    def gl_expose_event(self, glarea, event):
        debug("gl_expose_event(%s, %s)", glarea, event)
        self.present_fbo()


    def _do_paint_rgb24(self, img_data, x, y, width, height, rowstride, options, callbacks):
        debug("_do_paint_rgb24(x=%d, y=%d, width=%d, height=%d rowstride=%d)", x, y, width, height, rowstride)
        drawable = self.gl_init()
        if not drawable:
            debug("OpenGL cannot paint rgb24, drawable is not set")
            return False

        self.set_rgb24_paint_state()

        self.gl_marker("Painting RGB24 update at %d,%d, size %d,%d, stride is %d, row length %d" % (x, y, width, height, rowstride, rowstride/3))
        # Upload data as temporary RGB texture
        glBindTexture(GL_TEXTURE_RECTANGLE_ARB, self.textures[TEX_RGB])
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

        # Present update to screen
        self.present_fbo()
        # present_fbo has resetted state already

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
        gobject.idle_add(self.do_gl_yuv_paint, x, y, w, h, data, rowstrides, pixel_format, callbacks)

    def do_gl_yuv_paint(self, x, y, w, h, img_data, rowstrides, pixel_format, callbacks):
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
                    # Update FBO texture
                    self.render_yuv_update(x, y, x+w, y+h)
                    # Present it on screen
                    self.present_fbo()
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
            self.gl_marker("Creating new YUV textures")
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

        self.gl_marker("Updating YUV textures")
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

    def render_yuv_update(self, rx, ry, rw, rh):
        debug("render_yuv_update %sx%s at %sx%s pixel_format=%s", rw, rh, rx, ry, self.pixel_format)
        if self.pixel_format not in (YUV420P, YUV422P, YUV444P):
            #not ready to render yet
            return
        self.gl_marker("Painting YUV update")
        divs = get_subsampling_divs(self.pixel_format)
        glEnable(GL_FRAGMENT_PROGRAM_ARB)
        glBindProgramARB(GL_FRAGMENT_PROGRAM_ARB, self.yuv_shader[0])
        for texture, index in ((GL_TEXTURE0, 0), (GL_TEXTURE1, 1), (GL_TEXTURE2, 2)):
            glActiveTexture(texture)
            glBindTexture(GL_TEXTURE_RECTANGLE_ARB, self.textures[index])

        tw, th = self.texture_size
        debug("render_yuv_update texture_size=%s, size=%s", self.texture_size, self.size)
        glBegin(GL_QUADS)
        for x,y in ((rx, ry), (rx, ry+rh), (rx+rw, ry+rh), (rx+rw, ry)):
            ax = min(tw, x)
            ay = min(th, y)
            for texture, index in ((GL_TEXTURE0, 0), (GL_TEXTURE1, 1), (GL_TEXTURE2, 2)):
                (div_w, div_h) = divs[index]
                glMultiTexCoord2i(texture, ax/div_w, ay/div_h)
            glVertex2i(ax, ay)
        glEnd()
