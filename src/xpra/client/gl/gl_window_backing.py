# This file is part of Xpra.
# Copyright (C) 2013 Serviware (Arthur Huillet, <ahuillet@serviware.com>)
# Copyright (C) 2012, 2013 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

#only works with gtk2:
import os
from gtk import gdk
assert gdk
import gtk.gdkgl, gtk.gtkgl         #@UnresolvedImport
assert gtk.gdkgl is not None and gtk.gtkgl is not None
import gobject

from xpra.log import Logger, debug_if_env
log = Logger()
debug = debug_if_env(log, "XPRA_OPENGL_DEBUG")
OPENGL_DEBUG = os.environ.get("XPRA_OPENGL_DEBUG", "0")=="1"


from xpra.codecs.codec_constants import get_subsampling_divs
from xpra.client.gl.gl_check import get_DISPLAY_MODE
from xpra.client.gl.gl_colorspace_conversions import YUV2RGB_shader, RGBP2RGB_shader
from xpra.client.gtk2.window_backing import GTK2WindowBacking, fire_paint_callbacks
from OpenGL.GL import GL_PROJECTION, GL_MODELVIEW, \
    GL_UNPACK_ROW_LENGTH, GL_UNPACK_ALIGNMENT, \
    GL_TEXTURE_MAG_FILTER, GL_TEXTURE_MIN_FILTER, GL_NEAREST, \
    GL_UNSIGNED_BYTE, GL_LUMINANCE, GL_LINEAR, \
    GL_TEXTURE0, GL_TEXTURE1, GL_TEXTURE2, GL_QUADS, GL_COLOR_BUFFER_BIT, \
    GL_DONT_CARE, GL_TRUE, \
    GL_RGB, GL_RGBA, GL_BGR, GL_BGRA, \
    GL_BLEND, GL_ZERO, GL_ONE, \
    GL_FUNC_ADD, GL_ONE_MINUS_SRC_ALPHA, GL_SRC_ALPHA, \
    GL_TEXTURE_MAX_LEVEL, GL_TEXTURE_2D, \
    glBlendEquationSeparate, glBlendFuncSeparate, \
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


#debugging variables:
GL_DEBUG_OUTPUT = None
GL_DEBUG_OUTPUT_SYNCHRONOUS = None
gl_debug_callback = None
glInitStringMarkerGREMEDY = None
glStringMarkerGREMEDY = None
glInitFrameTerminatorGREMEDY = None
glFrameTerminatorGREMEDY = None
if OPENGL_DEBUG:
    try:
        from OpenGL.GL.KHR.debug import GL_DEBUG_OUTPUT, GL_DEBUG_OUTPUT_SYNCHRONOUS, glDebugMessageControl, glDebugMessageCallback, glInitDebugKHR
    except ImportError:
        debug("Unable to import GL_KHR_debug OpenGL extension. Debug output will be more limited.")
    try:
        from OpenGL.GL.GREMEDY.string_marker import glInitStringMarkerGREMEDY, glStringMarkerGREMEDY
        from OpenGL.GL.GREMEDY.frame_terminator import glInitFrameTerminatorGREMEDY, glFrameTerminatorGREMEDY
        from OpenGL.GL import GLDEBUGPROC #@UnresolvedImport
        def py_gl_debug_callback(source, error_type, error_id, severity, length, message, param):
            log.error("src %x type %x id %x severity %x length %d message %s", source, error_type, error_id, severity, length, message)
        gl_debug_callback = GLDEBUGPROC(py_gl_debug_callback)
    except ImportError:
        # This is normal- GREMEDY_string_marker is only available with OpenGL debuggers
        debug("Unable to import GREMEDY OpenGL extension. Debug output will be more limited.")
    debug("OpenGL debugging settings: "+
          "GL_DEBUG_OUTPUT=%s, GL_DEBUG_OUTPUT_SYNCHRONOUS=%s"+
          "gl_debug_callback=%s, "+
          "glInitStringMarkerGREMEDY=%s, glStringMarkerGREMEDY=%s, glInitFrameTerminatorGREMEDY=%s, glFrameTerminatorGREMEDY=%s",
            GL_DEBUG_OUTPUT, GL_DEBUG_OUTPUT_SYNCHRONOUS,
            gl_debug_callback, glInitStringMarkerGREMEDY, glStringMarkerGREMEDY,
            glInitFrameTerminatorGREMEDY, glFrameTerminatorGREMEDY)
from ctypes import c_char_p


# Texture number assignment
#  1 = Y plane
#  2 = U plane
#  3 = V plane
#  4 = RGB updates
#  5 = FBO texture (guaranteed up-to-date window contents)
# The first four are used to update the FBO,
# the FBO is what is painted on screen.
TEX_Y = 0
TEX_U = 1
TEX_V = 2
TEX_RGB = 3
TEX_FBO = 4

# Shader number assignment
YUV2RGB_SHADER = 0
RGBP2RGB_SHADER = 1

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

    def __init__(self, wid, w, h, has_alpha):
        GTK2WindowBacking.__init__(self, wid, w, h, has_alpha)
        display_mode = get_DISPLAY_MODE()
        try:
            self.glconfig = gtk.gdkgl.Config(mode=display_mode)
        except gtk.gdkgl.NoMatches:
            display_mode &= ~gtk.gdkgl.MODE_DOUBLE
            self.glconfig = gtk.gdkgl.Config(mode=display_mode)
        self._backing = gtk.gtkgl.DrawingArea(self.glconfig)
        #restoring missed masks:
        self._backing.set_events(self._backing.get_events() | gdk.POINTER_MOTION_MASK | gdk.POINTER_MOTION_HINT_MASK)
        if self._has_alpha:
            screen = self._backing.get_screen()
            rgba = screen.get_rgba_colormap()
            if rgba:
                self._backing.set_colormap(rgba)
            else:
                log.warn("failed to enable transparency on screen %s", screen)
                self._has_alpha = False
        self._backing.show()
        self._backing.connect("expose_event", self.gl_expose_event)
        self.textures = None # OpenGL texture IDs
        self.shaders = None
        self.pixel_format = None
        self.size = 0, 0
        self.texture_size = 0, 0
        self.gl_setup = False
        self.debug_setup = False
        self.paint_screen = False
        self._video_use_swscale = False
        self.draw_needs_refresh = False
        self.offscreen_fbo = None

    def __str__(self):
        return "GLPixmapBacking(%s, %s, %s)" % (self.wid, self.size, self.pixel_format)

    def init(self, w, h):
        #re-init gl projection with new dimensions
        #(see gl_init)
        if self.size!=(w, h):
            self.gl_setup = False
            self.size = w, h

    def gl_marker(self, msg):
        debug("%s.gl_marker(%s)", self, msg)
        if not bool(glStringMarkerGREMEDY):
            return
        c_string = c_char_p(msg)
        glStringMarkerGREMEDY(0, c_string)

    def gl_frame_terminator(self):
        debug("%s.gl_frame_terminator()", self)
        # Mark the end of the frame
        # This makes the debug output more readable especially when doing single-buffered rendering
        if not bool(glFrameTerminatorGREMEDY):
            return
        glFrameTerminatorGREMEDY()

    def gl_init_debug(self):
        #ensure python knows which scope we're talking about:
        global glInitStringMarkerGREMEDY, glStringMarkerGREMEDY
        global glInitFrameTerminatorGREMEDY, glFrameTerminatorGREMEDY
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
            #don't bother trying again for another window:
            glInitStringMarkerGREMEDY = None
        # Initialize frame_terminator GL debugging extension if available
        if glInitFrameTerminatorGREMEDY and glInitFrameTerminatorGREMEDY() == True:
            log.info("Enabling GL frame terminator debugging.")
        else:
            glFrameTerminatorGREMEDY = None
            #don't bother trying again for another window:
            glInitFrameTerminatorGREMEDY = None

    def gl_init_textures(self):
        assert self.offscreen_fbo is None
        assert self.shaders is None
        self.textures = glGenTextures(5)
        self.offscreen_fbo = glGenFramebuffers(1)
        debug("%s.gl_init_textures() textures: %s, offscreen fbo: %s", self, self.textures, self.offscreen_fbo)

    def gl_init_shaders(self):
        assert self.shaders is None
        # Create and assign fragment programs
        self.shaders = [ 1, 2 ]
        glGenProgramsARB(2, self.shaders)
        for progid, progstr in ((YUV2RGB_SHADER, YUV2RGB_shader), (RGBP2RGB_SHADER, RGBP2RGB_shader)):
            glBindProgramARB(GL_FRAGMENT_PROGRAM_ARB, self.shaders[progid])
            glProgramStringARB(GL_FRAGMENT_PROGRAM_ARB, GL_PROGRAM_FORMAT_ASCII_ARB, len(progstr), progstr)
            err = glGetString(GL_PROGRAM_ERROR_STRING_ARB)
            if err:
                #FIXME: maybe we should do something else here?
                log.error(err)

    def gl_init(self):
        drawable = self.gl_begin()
        w, h = self.size
        debug("%s.gl_init() GL Pixmap backing size: %d x %d, drawable=%s", self, w, h, drawable)
        if not drawable:
            return  None

        if not self.debug_setup:
            self.debug_setup = True
            self.gl_init_debug()

        if not self.gl_setup:
            self.gl_marker("Initializing GL context for window size %d x %d" % (w, h))
            # Initialize viewport and matrices for 2D rendering
            glViewport(0, 0, w, h)
            glMatrixMode(GL_PROJECTION)
            glLoadIdentity()
            glOrtho(0.0, w, h, 0.0, -1.0, 1.0)
            glMatrixMode(GL_MODELVIEW)
            # Could be more optimal to use vertex arrays:
            # glEnableClientState(GL_VERTEX_ARRAY)
            # glEnableClientState(GL_TEXTURE_COORD_ARRAY)

            # Clear background to transparent black
            glClearColor(0.0, 0.0, 0.0, 0.0)

            # Default state is good for YUV painting:
            #  - fragment program enabled
            #  - YUV fragment program bound
            #  - render to offscreen FBO
            if self.textures is None:
                self.gl_init_textures()

            # Define empty FBO texture and set rendering to FBO
            glEnable(GL_FRAGMENT_PROGRAM_ARB)
            glBindTexture(GL_TEXTURE_RECTANGLE_ARB, self.textures[TEX_FBO])
            # nvidia needs this even though we don't use mipmaps (repeated through this file):
            glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAX_LEVEL, 0)
            glTexImage2D(GL_TEXTURE_RECTANGLE_ARB, 0, GL_RGBA, w, h, 0, GL_RGBA, GL_UNSIGNED_BYTE, None)
            glBindFramebuffer(GL_FRAMEBUFFER, self.offscreen_fbo)
            glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_TEXTURE_RECTANGLE_ARB, self.textures[TEX_FBO], 0)
            glClear(GL_COLOR_BUFFER_BIT)

            # Create and assign fragment programs
            if not self.shaders:
                self.gl_init_shaders()

            # Bind program 0 for YUV painting by default
            glBindProgramARB(GL_FRAGMENT_PROGRAM_ARB, self.shaders[YUV2RGB_SHADER])
            self.gl_setup = True
        return drawable

    def close(self):
        #This seems to cause problems, so we rely
        #on destroying the context to clear textures and fbos...
        #if self.offscreen_fbo is not None:
        #    glDeleteFramebuffers(1, [self.offscreen_fbo])
        #    self.offscreen_fbo = None
        #if self.textures is not None:
        #    glDeleteTextures(self.textures)
        #    self.textures = None
        if self._backing:
            self._backing.destroy()
        GTK2WindowBacking.close(self)
        self.glconfig = None

    def gl_begin(self):
        if self._backing is None:
            return None     #closed already
        drawable = self._backing.get_gl_drawable()
        context = self._backing.get_gl_context()
        if drawable is None or context is None:
            log.error("%s.gl_begin() no drawable or context!", self)
            return None
        if not drawable.gl_begin(context):
            log.error("%s.gl_begin() cannot create rendering context!", self)
            return None
        return drawable

    def set_rgb_paint_state(self):
        # Set GL state for RGB painting:
        #    no fragment program
        #    only tex unit #0 active
        self.gl_marker("Switching to RGB paint state")
        glDisable(GL_FRAGMENT_PROGRAM_ARB);
        for texture in (GL_TEXTURE1, GL_TEXTURE2):
            glActiveTexture(texture)
            glDisable(GL_TEXTURE_RECTANGLE_ARB)
        glActiveTexture(GL_TEXTURE0);
        glEnable(GL_TEXTURE_RECTANGLE_ARB)

    def unset_rgb_paint_state(self):
        # Reset state to our default
        self.gl_marker("Switching back to YUV paint state")
        glEnable(GL_FRAGMENT_PROGRAM_ARB)

    def set_rgbP_paint_state(self):
        # Set GL state for planar RGB:
        #   change fragment program
        glBindProgramARB(GL_FRAGMENT_PROGRAM_ARB, self.shaders[RGBP2RGB_SHADER])

    def unset_rgbP_paint_state(self):
        # Reset state to our default (YUV painting):
        #   change fragment program
        glBindProgramARB(GL_FRAGMENT_PROGRAM_ARB, self.shaders[YUV2RGB_SHADER])

    def present_fbo(self, drawable):
        self.gl_marker("Presenting FBO on screen for drawable %s" % drawable)
        assert drawable
        # Change state to target screen instead of our FBO
        glBindFramebuffer(GL_FRAMEBUFFER, 0)

        if self._has_alpha:
            # transparent background:
            glClearColor(0.0, 0.0, 0.0, 0.0)
        else:
            # plain white no alpha:
            glClearColor(1.0, 1.0, 1.0, 1.0)

        # Draw FBO texture on screen
        self.set_rgb_paint_state()

        glBindTexture(GL_TEXTURE_RECTANGLE_ARB, self.textures[TEX_FBO])
        if self._has_alpha:
            # support alpha channel if present:
            glEnable(GL_BLEND)
            glBlendEquationSeparate(GL_FUNC_ADD, GL_FUNC_ADD)
            glBlendFuncSeparate(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA, GL_ONE, GL_ZERO)

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
            debug("%s.present_fbo() swapping buffers now", self)
            drawable.swap_buffers()
            # Clear the new backbuffer to illustrate that its contents are undefined
            glClear(GL_COLOR_BUFFER_BIT)
        else:
            glFlush()
        if self._has_alpha:
            glDisable(GL_BLEND)
        self.gl_frame_terminator()

        self.unset_rgb_paint_state()
        glBindFramebuffer(GL_FRAMEBUFFER, self.offscreen_fbo)
        debug("%s.present_fbo() done", self)

    def gl_expose_event(self, glarea, event):
        debug("%s.gl_expose_event(%s, %s)", self, glarea, event)
        drawable = self.gl_init()
        if not drawable:
            return
        try:
            self.present_fbo(drawable)
        finally:
            drawable.gl_end()

    def _do_paint_rgb32(self, img_data, x, y, width, height, rowstride, options, callbacks):
        #FIXME: we ought to be able to use
        #OpenGL blending and use premultiplied pixels directly... beats me!
        rgba = self.unpremultiply(img_data)
        return self._do_paint_rgb(32, rgba, x, y, width, height, rowstride, options, callbacks)

    def _do_paint_rgb24(self, img_data, x, y, width, height, rowstride, options, callbacks):
        return self._do_paint_rgb(24, img_data, x, y, width, height, rowstride, options, callbacks)

    def _do_paint_rgb(self, bpp, img_data, x, y, width, height, rowstride, options, callbacks):
        debug("%s._do_paint_rgb(%s, %s bytes, x=%d, y=%d, width=%d, height=%d, rowstride=%d)", self, bpp, len(img_data), x, y, width, height, rowstride)
        drawable = self.gl_init()
        if not drawable:
            debug("%s._do_paint_rgb(..) drawable is not set!", self)
            return False

        try:
            self.set_rgb_paint_state()

            bytes_per_pixel = bpp/8
            # Compute alignment and row length
            row_length = 0
            alignment = 1
            for a in [2, 4, 8]:
                # Check if we are a-aligned - ! (var & 0x1) means 2-aligned or better, 0x3 - 4-aligned and so on
                if (rowstride & a-1) == 0:
                    alignment = a
            # If number of extra bytes is greater than the alignment value,
            # then we also have to set row_length
            # Otherwise it remains at 0 (= width implicitely)
            if (rowstride - width * bytes_per_pixel) > a:
                row_length = width + (rowstride - width * bytes_per_pixel) / bytes_per_pixel

            rgb_format = options.get("rgb_format", None)
            self.gl_marker("%s %sbpp update at %d,%d, size %d,%d, stride is %d, row length %d, alignment %d" % (rgb_format, bpp, x, y, width, height, rowstride, row_length, alignment))
            # Upload data as temporary RGB texture
            if bpp==24:
                if rgb_format=="BGR":
                    pformat = GL_BGR
                else:
                    assert rgb_format in ("RGB", None), "invalid 24-bit format: %s" % rgb_format
                    pformat = GL_RGB
            else:
                assert bpp==32
                if rgb_format=="BGRA":
                    pformat = GL_BGRA
                else:
                    assert rgb_format in ("RGBA", None), "invalid 32-bit format: %s" % rgb_format
                    pformat = GL_RGBA

            glBindTexture(GL_TEXTURE_RECTANGLE_ARB, self.textures[TEX_RGB])
            glPixelStorei(GL_UNPACK_ROW_LENGTH, row_length)
            glPixelStorei(GL_UNPACK_ALIGNMENT, alignment)
            glTexParameteri(GL_TEXTURE_RECTANGLE_ARB, GL_TEXTURE_MAG_FILTER, GL_NEAREST)
            glTexParameteri(GL_TEXTURE_RECTANGLE_ARB, GL_TEXTURE_MIN_FILTER, GL_NEAREST)
            glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAX_LEVEL, 0)
            glTexImage2D(GL_TEXTURE_RECTANGLE_ARB, 0, GL_RGBA, width, height, 0, pformat, GL_UNSIGNED_BYTE, img_data)

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
            self.present_fbo(drawable)
            # present_fbo has reset state already
        finally:
            drawable.gl_end()
        return True

    def do_video_paint(self, img, x, y, enc_width, enc_height, width, height, options, callbacks):
        img.clone_pixel_data()
        gobject.idle_add(self.gl_paint_planar, img, x, y, enc_width, enc_height, width, height, callbacks)

    def gl_paint_planar(self, img, x, y, enc_width, enc_height, width, height, callbacks):
        #this function runs in the UI thread, no video_decoder lock held
        try:
            pixel_format = img.get_pixel_format()
            assert pixel_format in ("YUV420P", "YUV422P", "YUV444P", "GBRP"), "sorry the GL backing does not handle pixel format '%s' yet!" % (pixel_format)
            drawable = self.gl_init()
            if not drawable:
                debug("%s.gl_paint_planar() drawable is not set!", self)
                fire_paint_callbacks(callbacks, False)
                return
            try:
                self.update_planar_textures(x, y, enc_width, enc_height, img, pixel_format, scaling=(enc_width!=width or enc_height!=height))
                if self.paint_screen:
                    # Update FBO texture
                    x_scale, y_scale = 1, 1
                    if width!=enc_width or height!=enc_height:
                        x_scale = float(width)/enc_width
                        y_scale = float(height)/enc_height
                    self.render_planar_update(x, y, enc_width, enc_height, x_scale, y_scale)
                    # Present it on screen
                    self.present_fbo(drawable)
            finally:
                drawable.gl_end()
            fire_paint_callbacks(callbacks, True)
        except Exception, e:
            log.error("%s.gl_paint_planar(..) error: %s", self, e, exc_info=True)
            fire_paint_callbacks(callbacks, False)

    def update_planar_textures(self, x, y, width, height, img, pixel_format, scaling=False):
        assert x==0 and y==0
        assert self.textures is not None, "no OpenGL textures!"
        debug("%s.update_planar_textures%s", self, (x, y, width, height, img, pixel_format))

        divs = get_subsampling_divs(pixel_format)
        if self.pixel_format is None or self.pixel_format!=pixel_format or self.texture_size!=(width, height):
            self.pixel_format = pixel_format
            self.texture_size = (width, height)
            self.gl_marker("Creating new planar textures, pixel format %s" % pixel_format)
            # Create textures of the same size as the window's
            glEnable(GL_TEXTURE_RECTANGLE_ARB)

            for texture, index in ((GL_TEXTURE0, 0), (GL_TEXTURE1, 1), (GL_TEXTURE2, 2)):
                (div_w, div_h) = divs[index]
                glActiveTexture(texture)
                glBindTexture(GL_TEXTURE_RECTANGLE_ARB, self.textures[index])
                glEnable(GL_TEXTURE_RECTANGLE_ARB)
                mag_filter = GL_NEAREST
                if scaling or (div_w > 1 or div_h > 1):
                    mag_filter = GL_LINEAR
                glTexParameteri(GL_TEXTURE_RECTANGLE_ARB, GL_TEXTURE_MAG_FILTER, mag_filter)
                glTexParameteri(GL_TEXTURE_RECTANGLE_ARB, GL_TEXTURE_MIN_FILTER, GL_NEAREST)
                glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAX_LEVEL, 0)
                glTexImage2D(GL_TEXTURE_RECTANGLE_ARB, 0, GL_LUMINANCE, width/div_w, height/div_h, 0, GL_LUMINANCE, GL_UNSIGNED_BYTE, None)


        self.gl_marker("updating planar textures: %sx%s %s" % (width, height, pixel_format))
        U_width = 0
        U_height = 0
        rowstrides = img.get_rowstride()
        img_data = img.get_pixels()
        assert len(rowstrides)==3
        assert len(img_data)==3
        for texture, index in ((GL_TEXTURE0, 0), (GL_TEXTURE1, 1), (GL_TEXTURE2, 2)):
            (div_w, div_h) = divs[index]
            glActiveTexture(texture)
            glBindTexture(GL_TEXTURE_RECTANGLE_ARB, self.textures[index])
            glPixelStorei(GL_UNPACK_ROW_LENGTH, rowstrides[index])
            pixel_data = img_data[index]
            debug("texture %s: div=%s, rowstride=%s, %sx%s, data=%s bytes", index, divs[index], rowstrides[index], width/div_w, height/div_h, len(pixel_data))
            glTexSubImage2D(GL_TEXTURE_RECTANGLE_ARB, 0, x, y, width/div_w, height/div_h, GL_LUMINANCE, GL_UNSIGNED_BYTE, pixel_data)
            if index == 1:
                U_width = width/div_w
                U_height = height/div_h
            elif index == 2:
                if width/div_w != U_width:
                    log.error("Width of V plane is %d, differs from width of corresponding U plane (%d), pixel_format is %d", width/div_w, U_width, pixel_format)
                if height/div_h != U_height:
                    log.error("Height of V plane is %d, differs from height of corresponding U plane (%d), pixel_format is %d", height/div_h, U_height, pixel_format)

    def render_planar_update(self, rx, ry, rw, rh, x_scale=1, y_scale=1):
        debug("%s.render_planar_update%s pixel_format=%s", self, (rx, ry, rw, rh, x_scale, y_scale), self.pixel_format)
        if self.pixel_format not in ("YUV420P", "YUV422P", "YUV444P", "GBRP"):
            #not ready to render yet
            return
        assert rx==0 and ry==0
        if self.pixel_format == "GBRP":
            self.set_rgbP_paint_state()
        self.gl_marker("painting planar update, format %s" % self.pixel_format)
        divs = get_subsampling_divs(self.pixel_format)
        glEnable(GL_FRAGMENT_PROGRAM_ARB)
        for texture, index in ((GL_TEXTURE0, 0), (GL_TEXTURE1, 1), (GL_TEXTURE2, 2)):
            glActiveTexture(texture)
            glBindTexture(GL_TEXTURE_RECTANGLE_ARB, self.textures[index])

        tw, th = self.texture_size
        debug("%s.render_planar_update(..) texture_size=%s, size=%s", self, self.texture_size, self.size)
        glBegin(GL_QUADS)
        for x,y in ((rx, ry), (rx, ry+rh), (rx+rw, ry+rh), (rx+rw, ry)):
            ax = min(tw, x)
            ay = min(th, y)
            for texture, index in ((GL_TEXTURE0, 0), (GL_TEXTURE1, 1), (GL_TEXTURE2, 2)):
                (div_w, div_h) = divs[index]
                glMultiTexCoord2i(texture, ax/div_w, ay/div_h)
            glVertex2i(int(ax*x_scale), int(ay*y_scale))
        glEnd()
        if self.pixel_format == "GBRP":
            self.unset_rgbP_paint_state()
