# This file is part of Xpra.
# Copyright (C) 2013 Serviware (Arthur Huillet, <ahuillet@serviware.com>)
# Copyright (C) 2012-2017 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import struct
import time, math

from xpra.os_util import monotonic_time, strtobytes, hexstr, POSIX, DummyContextManager
from xpra.util import envint, envbool, repr_ellipsized
from xpra.log import Logger
log = Logger("opengl", "paint")
fpslog = Logger("opengl", "fps")

OPENGL_DEBUG = envbool("XPRA_OPENGL_DEBUG", False)
SCROLL_ENCODING = envbool("XPRA_SCROLL_ENCODING", True)
PAINT_FLUSH = envbool("XPRA_PAINT_FLUSH", True)

CURSOR_IDLE_TIMEOUT = envint("XPRA_CURSOR_IDLE_TIMEOUT", 6)
TEXTURE_CURSOR = envbool("XPRA_OPENGL_TEXTURE_CURSOR", False)

SAVE_BUFFERS = os.environ.get("XPRA_OPENGL_SAVE_BUFFERS")
if SAVE_BUFFERS not in ("png", "jpeg", None):
    log.warn("invalid value for XPRA_OPENGL_SAVE_BUFFERS: must be 'png' or 'jpeg'")
    SAVE_BUFFERS = None
if SAVE_BUFFERS:
    from OpenGL.GL import glGetTexImage
    import numpy
    from PIL import Image, ImageOps

from xpra.client.paint_colors import get_paint_box_color
from xpra.codecs.codec_constants import get_subsampling_divs
from xpra.client.window_backing_base import fire_paint_callbacks
from xpra.client.spinner import cv
from xpra.client.window_backing_base import WindowBackingBase
from xpra.client.gl.gl_check import GL_ALPHA_SUPPORTED, is_pyopengl_memoryview_safe
from xpra.client.gl.gl_colorspace_conversions import YUV2RGB_shader, RGBP2RGB_shader
from OpenGL import version as OpenGL_version
from OpenGL.error import GLError
from OpenGL.GL import \
    GL_PROJECTION, GL_MODELVIEW, \
    GL_UNPACK_ROW_LENGTH, GL_UNPACK_ALIGNMENT, \
    GL_TEXTURE_MAG_FILTER, GL_TEXTURE_MIN_FILTER, GL_NEAREST, \
    GL_UNSIGNED_BYTE, GL_LUMINANCE, GL_LINEAR, \
    GL_TEXTURE0, GL_TEXTURE1, GL_TEXTURE2, GL_QUADS, GL_POLYGON, GL_LINE_LOOP, GL_LINES, GL_COLOR_BUFFER_BIT, \
    GL_TEXTURE_WRAP_S, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_BORDER, \
    GL_DONT_CARE, GL_TRUE, GL_DEPTH_TEST, GL_SCISSOR_TEST, GL_LIGHTING, GL_DITHER, \
    GL_RGB, GL_RGBA, GL_BGR, GL_BGRA, GL_RGBA8, GL_RGB8, GL_RGB10_A2, GL_RGB565, GL_RGB5_A1, GL_RGBA4, \
    GL_UNSIGNED_INT_2_10_10_10_REV, GL_UNSIGNED_INT_10_10_10_2, GL_UNSIGNED_SHORT_5_6_5, \
    GL_BLEND, GL_ONE_MINUS_SRC_ALPHA, GL_SRC_ALPHA, \
    GL_TEXTURE_MAX_LEVEL, GL_TEXTURE_BASE_LEVEL, \
    GL_PERSPECTIVE_CORRECTION_HINT, GL_FASTEST, \
    glLineStipple, GL_LINE_STIPPLE, GL_POINTS, \
    glTexEnvi, GL_TEXTURE_ENV, GL_TEXTURE_ENV_MODE, GL_REPLACE, GL_TEXTURE_2D, \
    glHint, \
    glBlendFunc, \
    glActiveTexture, glTexSubImage2D, \
    glGetString, glViewport, glMatrixMode, glLoadIdentity, glOrtho, \
    glGenTextures, glDisable, \
    glBindTexture, glPixelStorei, glEnable, glEnablei, glBegin, glFlush, \
    glTexParameteri, \
    glTexImage2D, \
    glMultiTexCoord2i, \
    glTexCoord2i, glVertex2i, glEnd, \
    glClear, glClearColor, glLineWidth, glColor4f, \
    glDrawBuffer, glReadBuffer
from OpenGL.GL.ARB.texture_rectangle import GL_TEXTURE_RECTANGLE_ARB
from OpenGL.GL.ARB.vertex_program import glGenProgramsARB, \
    glBindProgramARB, glProgramStringARB, GL_PROGRAM_ERROR_STRING_ARB, GL_PROGRAM_FORMAT_ASCII_ARB
from OpenGL.GL.ARB.fragment_program import GL_FRAGMENT_PROGRAM_ARB
from OpenGL.GL.ARB.framebuffer_object import GL_FRAMEBUFFER, GL_DRAW_FRAMEBUFFER, GL_READ_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_COLOR_ATTACHMENT1, \
    glGenFramebuffers, glBindFramebuffer, glFramebufferTexture2D, glBlitFramebuffer


PIXEL_FORMAT_TO_CONSTANT = {
    "r210"  : GL_BGRA,
    "R210"  : GL_RGBA,
    "BGR"   : GL_BGR,
    "RGB"   : GL_RGB,
    "BGRA"  : GL_BGRA,
    "BGRX"  : GL_BGRA,
    "RGBA"  : GL_RGBA,
    "RGBX"  : GL_RGBA,
    "BGR565": GL_RGB,
    "RGB565": GL_RGB,
    }
PIXEL_FORMAT_TO_DATATYPE = {
    "r210"  : GL_UNSIGNED_INT_2_10_10_10_REV,
    "R210"  : GL_UNSIGNED_INT_10_10_10_2,
    "RGB565": GL_UNSIGNED_SHORT_5_6_5,
    "BGR565": GL_UNSIGNED_SHORT_5_6_5,
    "BGR"   : GL_UNSIGNED_BYTE,
    "RGB"   : GL_UNSIGNED_BYTE,
    "BGRA"  : GL_UNSIGNED_BYTE,
    "BGRX"  : GL_UNSIGNED_BYTE,
    "RGBA"  : GL_UNSIGNED_BYTE,
    "RGBX"  : GL_UNSIGNED_BYTE,
    }
CONSTANT_TO_PIXEL_FORMAT = {
    GL_BGR   : "BGR",
    GL_RGB   : "RGB",
    GL_BGRA  : "BGRA",
    GL_RGBA  : "RGBA",
    }
INTERNAL_FORMAT_TO_STR = {
    GL_RGB10_A2     : "RGB10_A2",
    GL_RGBA8        : "RGBA8",
    GL_RGB8         : "RGB8",
    GL_RGB565       : "RGB565",
    GL_RGB5_A1      : "RGB5_A1",
    GL_RGBA4        : "RGBA4",
    }
DATATYPE_TO_STR = {
    GL_UNSIGNED_INT_2_10_10_10_REV  : "UNSIGNED_INT_2_10_10_10_REV",
    GL_UNSIGNED_INT_10_10_10_2      : "UNSIGNED_INT_10_10_10_2",
    GL_UNSIGNED_BYTE                : "UNSIGNED_BYTE",
    GL_UNSIGNED_SHORT_5_6_5         : "UNSIGNED_SHORT_5_6_5",
    }

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
        log("Unable to import GL_KHR_debug OpenGL extension. Debug output will be more limited.")
    try:
        from OpenGL.GL.GREMEDY.string_marker import glInitStringMarkerGREMEDY, glStringMarkerGREMEDY
        from OpenGL.GL.GREMEDY.frame_terminator import glInitFrameTerminatorGREMEDY, glFrameTerminatorGREMEDY
        from OpenGL.GL import GLDEBUGPROC #@UnresolvedImport
        def py_gl_debug_callback(source, error_type, error_id, severity, length, message, param):
            log.error("src %x type %x id %x severity %x length %d message %s, param=%s", source, error_type, error_id, severity, length, message, param)
        gl_debug_callback = GLDEBUGPROC(py_gl_debug_callback)
    except ImportError:
        # This is normal- GREMEDY_string_marker is only available with OpenGL debuggers
        log("Unable to import GREMEDY OpenGL extension. Debug output will be more limited.")
    log("OpenGL debugging settings: "+
          "GL_DEBUG_OUTPUT=%s, GL_DEBUG_OUTPUT_SYNCHRONOUS=%s"+
          "gl_debug_callback=%s, "+
          "glInitStringMarkerGREMEDY=%s, glStringMarkerGREMEDY=%s, glInitFrameTerminatorGREMEDY=%s, glFrameTerminatorGREMEDY=%s",
            GL_DEBUG_OUTPUT, GL_DEBUG_OUTPUT_SYNCHRONOUS,
            gl_debug_callback, glInitStringMarkerGREMEDY, glStringMarkerGREMEDY,
            glInitFrameTerminatorGREMEDY, glFrameTerminatorGREMEDY)
from ctypes import c_char_p

try:
    import OpenGL_accelerate            #@UnresolvedImport
except:
    OpenGL_accelerate = None
zerocopy_upload = bool(OpenGL_accelerate) and envbool("XPRA_ZEROCOPY_OPENGL_UPLOAD", True) and is_pyopengl_memoryview_safe(OpenGL_version.__version__, OpenGL_accelerate.__version__)
try:
    buffer_type = buffer
except:
    #not defined in py3k..
    buffer_type = None


if POSIX:
    from xpra.gtk_common.error import xsync
    paint_context_manager = xsync
else:
    paint_context_manager = DummyContextManager()

def set_texture_level(target=GL_TEXTURE_RECTANGLE_ARB):
    #only really needed with some drivers (NVidia)
    #may cause errors with older drivers:
    try:
        glTexParameteri(target, GL_TEXTURE_MIN_FILTER, GL_LINEAR)
    except:
        pass


# Texture number assignment
# The first four are used to update the FBO,
# the FBO is what is painted on screen.
TEX_Y = 0
TEX_U = 1
TEX_V = 2
TEX_RGB = 3
TEX_FBO = 4         #FBO texture (guaranteed up-to-date window contents)
TEX_TMP_FBO = 5
if TEXTURE_CURSOR:
    TEX_CURSOR = 6
    N_TEXTURES = 7
else:
    TEX_CURSOR = -1
    N_TEXTURES = 6

# Shader number assignment
YUV2RGB_SHADER = 0
RGBP2RGB_SHADER = 1

"""
The logic is as follows:

We create an OpenGL framebuffer object, which will be always up-to-date with the latest windows contents.
This framebuffer object is updated with YUV painting and RGB painting. It is presented on screen by drawing a
textured quad when requested, that is: after each YUV or RGB painting operation, and upon receiving an expose event.
The use of a intermediate framebuffer object is the only way to guarantee that the client keeps an always fully up-to-date
window image, which is critical because of backbuffer content losses upon buffer swaps or offscreen window movement.
"""
class GLWindowBackingBase(WindowBackingBase):

    RGB_MODES = ["YUV420P", "YUV422P", "YUV444P", "GBRP", "BGRA", "BGRX", "RGBA", "RGBX", "RGB", "BGR"]
    HAS_ALPHA = GL_ALPHA_SUPPORTED

    def __init__(self, wid, window_alpha, pixel_depth=0):
        self.wid = wid
        self.texture_pixel_format = None
        #this is the pixel format we are currently updating the fbo with
        #can be: "YUV420P", "YUV422P", "YUV444P", "GBRP" or None when not initialized yet.
        self.pixel_format = None
        self.textures = None # OpenGL texture IDs
        self.shaders = None
        self.texture_size = 0, 0
        self.gl_setup = False
        self.debug_setup = False
        self.border = None
        self.paint_screen = False
        self.paint_spinner = False
        self.offscreen_fbo = None
        self.tmp_fbo = None
        self.pending_fbo_paint = []
        self.last_flush = monotonic_time()

        WindowBackingBase.__init__(self, wid, window_alpha and GL_ALPHA_SUPPORTED)

        self.init_gl_config(window_alpha)
        self.init_backing()
        self.bit_depth = self.get_bit_depth(pixel_depth)
        self.init_formats()
        self.draw_needs_refresh = False
        self._backing.show()

    def init_gl_config(self, window_alpha):
        raise NotImplementedError()

    def init_backing(self):
        raise NotImplementedError()

    def gl_context(self):
        raise NotImplementedError()

    def do_gl_show(self, rect_count):
        raise NotImplementedError()

    def is_double_buffered(self):
        raise NotImplementedError()


    def get_bit_depth(self, pixel_depth=0):
        return pixel_depth or 24

    def init_formats(self):
        self.RGB_MODES = list(GLWindowBackingBase.RGB_MODES)
        if self.bit_depth==30:
            self.internal_format = GL_RGB10_A2
            self.RGB_MODES.append("r210")
        elif self.bit_depth==16:
            if self._alpha_enabled:
                if envbool("XPRA_GL_RGBA4", True):
                    self.internal_format = GL_RGBA4
                else:
                    self.internal_format = GL_RGB5_A1
                    #too much of a waste to enable?
                    self.RGB_MODES.append("r210")
            else:
                self.internal_format = GL_RGB565
                self.RGB_MODES.append("BGR565")
                self.RGB_MODES.append("RGB565")
        else:
            #assume 24:
            if self._alpha_enabled:
                self.internal_format = GL_RGBA8
            else:
                self.internal_format = GL_RGB8
        #(pixels are always stored in 32bpp - but this makes it clearer when we do/don't support alpha)
        if self._alpha_enabled:
            self.texture_pixel_format = GL_RGBA
        else:
            self.texture_pixel_format = GL_RGB
        log("init_formats() texture pixel format=%s, internal format=%s, rgb modes=%s", ["GL_RGB", "GL_RGBA"][self._alpha_enabled], INTERNAL_FORMAT_TO_STR.get(self.internal_format), self.RGB_MODES)

    def get_encoding_properties(self):
        props = WindowBackingBase.get_encoding_properties(self)
        if SCROLL_ENCODING:
            props["encoding.scrolling"] = True
        props["encoding.bit-depth"] = self.bit_depth
        return props


    def __repr__(self):
        return "GLWindowBacking(%s, %s, %s)" % (self.wid, self.size, self.pixel_format)

    def init(self, ww, wh, bw, bh):
        #re-init gl projection with new dimensions
        #(see gl_init)
        if self.size!=(bw, bh):
            self.gl_setup = False
            self.size = bw, bh
        self.render_size = ww, wh

    def gl_marker(self, *msg):
        log(*msg)
        if not bool(glStringMarkerGREMEDY):
            return
        try:
            s = "%s" % msg
        except:
            s = str(msg)
        c_string = c_char_p(s)
        glStringMarkerGREMEDY(0, c_string)

    def gl_frame_terminator(self):
        log("%s.gl_frame_terminator()", self)
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
        self.textures = glGenTextures(N_TEXTURES)
        self.offscreen_fbo = glGenFramebuffers(1)
        self.tmp_fbo = glGenFramebuffers(1)
        log("%s.gl_init_textures() textures: %s, offscreen fbo: %s, tmp fbo: %s", self, self.textures, self.offscreen_fbo, self.tmp_fbo)

    def gl_init_shaders(self):
        assert self.shaders is None
        # Create and assign fragment programs
        self.shaders = [ 1, 2 ]
        glGenProgramsARB(2, self.shaders)
        for name, progid, progstr in (("YUV2RGB", YUV2RGB_SHADER, YUV2RGB_shader), ("RGBP2RGB", RGBP2RGB_SHADER, RGBP2RGB_shader)):
            glBindProgramARB(GL_FRAGMENT_PROGRAM_ARB, self.shaders[progid])
            glProgramStringARB(GL_FRAGMENT_PROGRAM_ARB, GL_PROGRAM_FORMAT_ASCII_ARB, len(progstr), progstr)
            err = glGetString(GL_PROGRAM_ERROR_STRING_ARB)
            if err:
                log.error("OpenGL shader %s failed:", name)
                log.error(" %s", err)
                raise Exception("OpenGL shader %s setup failure: %s" % (name, err))
            else:
                log("%s shader initialized", name)

    def gl_init(self):
        #must be called within a context!
        #performs init if needed
        if not self.debug_setup:
            self.debug_setup = True
            self.gl_init_debug()

        if not self.gl_setup:
            w, h = self.size
            self.gl_marker("Initializing GL context for window size %s, backing size %s", self.render_size, self.size)
            # Initialize viewport and matrices for 2D rendering
            x, _, _, y = self.offsets
            glViewport(x, y, w, h)
            glMatrixMode(GL_PROJECTION)
            glLoadIdentity()
            glOrtho(0.0, w, h, 0.0, -1.0, 1.0)
            glMatrixMode(GL_MODELVIEW)
            # Mesa docs claim: this hint can improve the speed of texturing
            #when perspective-correct texture coordinate interpolation isn't needed,
            #such as when using a glOrtho() projection:
            glHint(GL_PERSPECTIVE_CORRECTION_HINT, GL_FASTEST)
            # Could be more optimal to use vertex arrays:
            # glEnableClientState(GL_VERTEX_ARRAY)
            # glEnableClientState(GL_TEXTURE_COORD_ARRAY)

            # Clear background to transparent black
            glClearColor(0.0, 0.0, 0.0, 0.0)

            # we don't use the depth (2D only):
            glDisable(GL_DEPTH_TEST)
            glDisable(GL_SCISSOR_TEST)
            glDisable(GL_LIGHTING)
            glDisable(GL_DITHER)
            # only do alpha blending in present_fbo:
            glDisable(GL_BLEND)

            # Default state is good for YUV painting:
            #  - fragment program enabled
            #  - YUV fragment program bound
            #  - render to offscreen FBO
            if self.textures is None:
                self.gl_init_textures()

            # Define empty tmp FBO
            target = GL_TEXTURE_RECTANGLE_ARB
            glBindTexture(target, self.textures[TEX_TMP_FBO])
            set_texture_level(target)
            glTexImage2D(target, 0, self.internal_format, w, h, 0, self.texture_pixel_format, GL_UNSIGNED_BYTE, None)
            glBindFramebuffer(GL_FRAMEBUFFER, self.tmp_fbo)
            glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, target, self.textures[TEX_TMP_FBO], 0)
            glClear(GL_COLOR_BUFFER_BIT)

            # Define empty FBO texture and set rendering to FBO
            glBindTexture(target, self.textures[TEX_FBO])
            # nvidia needs this even though we don't use mipmaps (repeated through this file):
            set_texture_level(target)
            glTexImage2D(target, 0, self.internal_format, w, h, 0, self.texture_pixel_format, GL_UNSIGNED_BYTE, None)
            glBindFramebuffer(GL_FRAMEBUFFER, self.offscreen_fbo)
            glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, target, self.textures[TEX_FBO], 0)
            glClear(GL_COLOR_BUFFER_BIT)

            glBindTexture(target, 0)

            # Create and assign fragment programs
            if not self.shaders:
                self.gl_init_shaders()

            # Bind program 0 for YUV painting by default
            glBindProgramARB(GL_FRAGMENT_PROGRAM_ARB, self.shaders[YUV2RGB_SHADER])
            self.gl_setup = True

    def close(self):
        #This seems to cause problems, so we rely
        #on destroying the context to clear textures and fbos...
        #if self.offscreen_fbo is not None:
        #    glDeleteFramebuffers(1, [self.offscreen_fbo])
        #    self.offscreen_fbo = None
        #if self.textures is not None:
        #    glDeleteTextures(self.textures)
        #    self.textures = None
        b = self._backing
        if b:
            self._backing = None
            b.destroy()


    def paint_scroll(self, scroll_data, options, callbacks):
        flush = options.intget("flush", 0)
        self.idle_add(self.do_scroll_paints, scroll_data, flush, callbacks)

    def do_scroll_paints(self, scrolls, flush=0, callbacks=[]):
        log("do_scroll_paints%s", (scrolls, flush))
        context = self.gl_context()
        if not context:
            log("%s.do_scroll_paints(..) no context!", self)
            fire_paint_callbacks(callbacks, False, "no opengl context")
            return
        def fail(msg):
            log.error("Error: %s", msg)
            fire_paint_callbacks(callbacks, False, msg)
        with context:
            bw, bh = self.size
            #paste from offscreen to tmp with delta offset:
            glBindFramebuffer(GL_READ_FRAMEBUFFER, self.offscreen_fbo)
            target = GL_TEXTURE_RECTANGLE_ARB
            glEnable(target)
            glBindTexture(target, self.textures[TEX_FBO])
            glFramebufferTexture2D(GL_READ_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, target, self.textures[TEX_FBO], 0)
            glReadBuffer(GL_COLOR_ATTACHMENT0)

            glBindFramebuffer(GL_DRAW_FRAMEBUFFER, self.tmp_fbo)
            glBindTexture(target, self.textures[TEX_TMP_FBO])
            glFramebufferTexture2D(GL_DRAW_FRAMEBUFFER, GL_COLOR_ATTACHMENT1, target, self.textures[TEX_TMP_FBO], 0)
            glDrawBuffer(GL_COLOR_ATTACHMENT1)

            #copy current fbo:
            glBlitFramebuffer(0, 0, bw, bh,
                              0, 0, bw, bh,
                              GL_COLOR_BUFFER_BIT, GL_NEAREST)

            for x,y,w,h,xdelta,ydelta in scrolls:
                if abs(xdelta)>=bw:
                    fail("invalid xdelta value: %i, backing width is %i" % (xdelta, bw))
                    continue
                if abs(ydelta)>=bh:
                    fail("invalid ydelta value: %i, backing height is %i" % (ydelta, bh))
                    continue
                if ydelta==0 and xdelta==0:
                    fail("scroll has no delta!")
                    continue
                if w<=0 or h<=0:
                    fail("invalid scroll area size: %ix%i" % (w, h))
                    continue
                #these should be errors,
                #but desktop-scaling can cause a mismatch between the backing size
                #and the real window size server-side.. so we clamp the dimensions instead
                if x+w>bw:
                    w = bw-x
                if y+h>bh:
                    h = bh-y
                if x+w+xdelta>bw:
                    w = bw-x-xdelta
                    if w<=0:
                        continue        #nothing left!
                if y+h+ydelta>bh:
                    h = bh-y-ydelta
                    if h<=0:
                        continue        #nothing left!
                if x+xdelta<0:
                    fail("horizontal scroll by %i: rectangle %s overflows the backing buffer size %s" % (xdelta, (x, y, w, h), self.size))
                    continue
                if y+ydelta<0:
                    fail("vertical scroll by %i: rectangle %s overflows the backing buffer size %s" % (ydelta, (x, y, w, h), self.size))
                    continue
                #opengl buffer is upside down, so we must invert Y coordinates: bh-(..)
                glBlitFramebuffer(x, bh-y, x+w, bh-(y+h),
                                  x+xdelta, bh-(y+ydelta), x+w+xdelta, bh-(y+h+ydelta),
                                  GL_COLOR_BUFFER_BIT, GL_NEAREST)
                glFlush()

            #now swap references to tmp and offscreen so tmp becomes the new offscreen:
            tmp = self.offscreen_fbo
            self.offscreen_fbo = self.tmp_fbo
            self.tmp_fbo = tmp
            tmp = self.textures[TEX_FBO]
            self.textures[TEX_FBO] = self.textures[TEX_TMP_FBO]
            self.textures[TEX_TMP_FBO] = tmp

            #restore normal paint state:
            glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, target, self.textures[TEX_FBO], 0)
            glBindFramebuffer(GL_READ_FRAMEBUFFER, self.offscreen_fbo)
            glBindFramebuffer(GL_DRAW_FRAMEBUFFER, self.offscreen_fbo)
            glBindFramebuffer(GL_FRAMEBUFFER, self.offscreen_fbo)

            glBindTexture(target, 0)
            glDisable(target)
            self.paint_box("scroll", True, x+xdelta, y+ydelta, x+w+xdelta, y+h+ydelta)
            self.present_fbo(0, 0, bw, bh, flush)
            fire_paint_callbacks(callbacks, True)

    def present_fbo(self, x, y, w, h, flush=0):
        log("present_fbo: adding %s to pending paint list (size=%i), flush=%s, paint_screen=%s", (x, y, w, h), len(self.pending_fbo_paint), flush, self.paint_screen)
        self.pending_fbo_paint.append((x, y, w, h))
        if not self.paint_screen:
            return
        #flush>0 means we should wait for the final flush=0 paint
        if flush==0 or not PAINT_FLUSH:
            try:
                with paint_context_manager:
                    self.do_present_fbo()
            except Exception as e:
                log.error("Error presenting FBO:")
                log.error(" %s", e)
                log("Error presenting FBO", exc_info=True)

    def do_present_fbo(self):
        bw, bh = self.size
        ww, wh = self.render_size
        rect_count = len(self.pending_fbo_paint)
        if self.is_double_buffered() or bw!=ww or bh!=wh:
            #refresh the whole window:
            rectangles = ((0, 0, bw, bh), )
        else:
            #paint just the rectangles we have accumulated:
            rectangles = self.pending_fbo_paint
        self.pending_fbo_paint = []
        log("do_present_fbo: painting %s", rectangles)

        if SAVE_BUFFERS:
            self.save_FBO()

        self.gl_marker("Presenting FBO on screen")
        # Change state to target screen instead of our FBO
        glBindFramebuffer(GL_FRAMEBUFFER, 0)
        glBindFramebuffer(GL_DRAW_FRAMEBUFFER, 0)

        if self._alpha_enabled:
            # transparent background:
            glClearColor(0.0, 0.0, 0.0, 0.0)
        else:
            # plain white no alpha:
            glClearColor(1.0, 1.0, 1.0, 1.0)

        #viewport for painting to window:
        x, _, _, y = self.offsets
        glViewport(x, y, ww, wh)
        target = GL_TEXTURE_RECTANGLE_ARB
        if ww!=bw or wh!=bh:
            glTexParameteri(target, GL_TEXTURE_MAG_FILTER, GL_LINEAR)
            glTexParameteri(target, GL_TEXTURE_MIN_FILTER, GL_LINEAR)

        # Draw FBO texture on screen
        glEnable(target)      #redundant - done in rgb paint state
        glBindTexture(target, self.textures[TEX_FBO])
        if self._alpha_enabled:
            # support alpha channel if present:
            glEnablei(GL_BLEND, self.textures[TEX_FBO])
            glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)
        glTexEnvi(GL_TEXTURE_ENV, GL_TEXTURE_ENV_MODE, GL_REPLACE)
        glBegin(GL_QUADS)
        for x,y,w,h in rectangles:
            #note how we invert coordinates..
            tx1, ty1, tx2, ty2 = x, bh-y,  x+w, bh-y-h
            vx1, vy1, vx2, vy2 = x, y,     x+w, y+h
            glTexCoord2i(tx1, ty1)
            glVertex2i(vx1, vy1)        #top-left of window viewport
            glTexCoord2i(tx1, ty2)
            glVertex2i(vx1, vy2)        #bottom-left of window viewport
            glTexCoord2i(tx2, ty2)
            glVertex2i(vx2, vy2)        #bottom-right of window viewport
            glTexCoord2i(tx2, ty1)
            glVertex2i(vx2, vy1)        #top-right of window viewport
        glEnd()
        glBindTexture(target, 0)
        glDisable(target)

        if self.pointer_overlay:
            self.draw_pointer()

        if self.paint_spinner:
            #add spinner:
            self.draw_spinner()

        if self.border and self.border.shown:
            self.draw_border()

        # Show the backbuffer on screen
        glFlush()
        self.gl_show(rect_count)
        self.gl_frame_terminator()

        #restore pbo viewport
        glViewport(0, 0, bw, bh)
        glTexParameteri(target, GL_TEXTURE_MAG_FILTER, GL_NEAREST)
        glTexParameteri(target, GL_TEXTURE_MIN_FILTER, GL_NEAREST)
        log("%s(%s, %s)", glBindFramebuffer, GL_FRAMEBUFFER, self.offscreen_fbo)
        glBindFramebuffer(GL_FRAMEBUFFER, self.offscreen_fbo)
        log("%s.do_present_fbo() done", self)

    def save_FBO(self):
        bw, bh = self.size
        glEnable(GL_TEXTURE_RECTANGLE_ARB)
        glBindFramebuffer(GL_READ_FRAMEBUFFER, self.offscreen_fbo)
        glBindTexture(GL_TEXTURE_RECTANGLE_ARB, self.textures[TEX_FBO])
        glFramebufferTexture2D(GL_READ_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_TEXTURE_RECTANGLE_ARB, self.textures[TEX_FBO], 0)
        glReadBuffer(GL_COLOR_ATTACHMENT0)
        glViewport(0, 0, bw, bh)
        size = bw*bh*4
        data = numpy.empty(size)
        img_data = glGetTexImage(GL_TEXTURE_RECTANGLE_ARB, 0, GL_BGRA, GL_UNSIGNED_BYTE, data)
        img = Image.frombuffer("RGBA", (bw, bh), img_data, "raw", "BGRA", bw*4)
        img = ImageOps.flip(img)
        kwargs = {}
        if SAVE_BUFFERS=="jpeg":
            kwargs = {
                      "quality"     : 0,
                      "optimize"    : False,
                      }
        t = time.time()
        tstr = time.strftime("%H-%M-%S", time.localtime(t))
        filename = "./W%i-FBO-%s.%03i.%s" % (self.wid, tstr, (t*1000)%1000, SAVE_BUFFERS)
        log("do_present_fbo: saving %4ix%-4i pixels, %7i bytes to %s", bw, bh, size, filename)
        img.save(filename, SAVE_BUFFERS, **kwargs)
        glBindFramebuffer(GL_READ_FRAMEBUFFER, 0)
        glBindTexture(GL_TEXTURE_RECTANGLE_ARB, 0)
        glDisable(GL_TEXTURE_RECTANGLE_ARB)

    def draw_pointer(self):
        x, y, _, _, size, start_time = self.pointer_overlay
        elapsed = monotonic_time()-start_time
        log("pointer_overlay=%s, elapsed=%.1f, timeout=%s, cursor-data=%s", self.pointer_overlay, elapsed, CURSOR_IDLE_TIMEOUT, (self.cursor_data or [])[:7])
        if elapsed>=CURSOR_IDLE_TIMEOUT:
            #timeout - stop showing it:
            self.pointer_overlay = None
            return

        if not self.cursor_data:
            #paint a fake one:
            alpha = max(0, (5.0-elapsed)/5.0)
            lw = 2
            glLineWidth(lw)
            glBegin(GL_LINES)
            glColor4f(0, 0, 0, alpha)
            glVertex2i(x-size, y-lw//2)
            glVertex2i(x+size, y-lw//2)
            glVertex2i(x, y-size)
            glVertex2i(x, y+size)
            glEnd()
            return

        cw = self.cursor_data[3]
        ch = self.cursor_data[4]
        if TEXTURE_CURSOR:
            #paint the texture containing the cursor:
            #glActiveTexture(GL_TEXTURE1)
            target = GL_TEXTURE_2D
            glEnable(target)
            glBindTexture(target, self.textures[TEX_CURSOR])
            self.upload_cursor_texture(target, self.cursor_data)

            #glEnablei(GL_BLEND, self.textures[TEX_CURSOR])
            #glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)
            #from OpenGL.GL import GL_REPLACE, GL_TEXTURE_2D, GL_COMBINE, GL_DECAL, GL_MODULATE, GL_ADD
            #glTexEnvi(GL_TEXTURE_ENV, GL_TEXTURE_ENV_MODE, GL_COMBINE)  #GL_REPLACE, GL_BLEND, GL_MODULATE

            glBegin(GL_QUADS)
            glTexCoord2i(0, 0)
            glVertex2i(x, y)
            glTexCoord2i(0, 1)
            glVertex2i(x, y+ch)
            glTexCoord2i(1, 1)
            glVertex2i(x+cw, y+ch)
            glTexCoord2i(1, 0)
            glVertex2i(x+cw, y)
            glEnd()

            glBindTexture(target, 0)
            glDisable(target)
            #glActiveTexture(GL_TEXTURE0)
        else:
            #FUGLY: paint each pixel separately..
            pixels = self.cursor_data[8]
            p = struct.unpack("B"*(cw*ch*4), pixels)
            glLineWidth(1)
            #TODO: use VBO arrays to make this faster
            for cx in range(cw):
                for cy in range(ch):
                    i = cx*4+cy*cw*4
                    if p[i+3]>=64:
                        glBegin(GL_POINTS)
                        glColor4f(p[i]/256.0, p[i+1]/256.0, p[i+2]/256.0, p[i+3]/256.0)
                        glVertex2i(x+cx, y+cy)
                        glEnd()

    def upload_cursor_texture(self, target, cursor_data):
        width = cursor_data[3]
        height = cursor_data[4]
        pixels = cursor_data[8]
        if len(pixels)<width*4*height:
            log.error("Error: invalid cursor pixel buffer for %ix%i", width, height)
            log.error(" expected %i bytes but got %i", width*height*4, len(pixels))
            log.error(" %s", repr_ellipsized(hexstr(pixels)))
            return
        upload, pixel_data = self.pixels_for_upload(pixels)
        rgb_format = "BGRA"
        self.set_alignment(width, width*4, rgb_format)
        glTexParameteri(target, GL_TEXTURE_MAG_FILTER, GL_NEAREST)
        glTexParameteri(target, GL_TEXTURE_MIN_FILTER, GL_NEAREST)
        set_texture_level(target)
        glTexParameteri(target, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_BORDER)
        glTexParameteri(target, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_BORDER)
        glTexImage2D(target, 0, GL_RGBA8, width, height, 0, GL_BGRA, GL_UNSIGNED_BYTE, pixel_data)
        log("GL cursor %ix%i uploaded %i bytes of %s pixel data using %s", width, height, len(pixels), rgb_format, upload)

    def draw_spinner(self):
        bw, bh = self.size
        dim = min(bw/3.0, bh/3.0)
        t = monotonic_time()
        count = int(t*4.0)
        bx = bw//2
        by = bh//2
        for i in range(8):      #8 lines
            c = cv.trs[count%8][i]
            mi1 = math.pi*i/4-math.pi/16
            mi2 = math.pi*i/4+math.pi/16
            si1 = math.sin(mi1)
            si2 = math.sin(mi2)
            ci1 = math.cos(mi1)
            ci2 = math.cos(mi2)
            glBegin(GL_POLYGON)
            glColor4f(c, c, c, 1)
            glVertex2i(int(bx+si1*10), int(by+ci1*10))
            glVertex2i(int(bx+si1*dim), int(by+ci1*dim))
            glVertex2i(int(bx+si2*dim), int(by+ci2*dim))
            glVertex2i(int(bx+si2*10), int(by+ci2*10))
            glEnd()

    def draw_border(self):
        bw, bh = self.size
        #double size since half the line will be off-screen
        log("draw_border: %s", self.border)
        glLineWidth(self.border.size*2)
        glBegin(GL_LINE_LOOP)
        glColor4f(self.border.red, self.border.green, self.border.blue, self.border.alpha)
        for px,py in ((0, 0), (bw, 0), (bw, bh), (0, bh)):
            glVertex2i(px, py)
        glEnd()

    def set_cursor_data(self, cursor_data):
        if (not cursor_data or len(cursor_data)==1) and self.default_cursor_data:
            cursor_data = ["raw"] + self.default_cursor_data
        if not cursor_data:
            return
        self.cursor_data = cursor_data


    def paint_box(self, encoding, is_delta, x, y, w, h):
        #show region being painted if debug paint box is enabled only:
        if self.paint_box_line_width<=0:
            return
        glLineWidth(self.paint_box_line_width+0.5+int(encoding=="scroll")*2)
        if is_delta:
            glLineStipple(1, 0xaaaa)
            glEnable(GL_LINE_STIPPLE)
        glBegin(GL_LINE_LOOP)
        color = get_paint_box_color(encoding)
        log("Painting colored box around %s screen update using: %s (delta=%s)", encoding, color, is_delta)
        glColor4f(*color)
        for px,py in ((x, y), (x+w, y), (x+w, y+h), (x, y+h)):
            glVertex2i(px, py)
        glEnd()
        if is_delta:
            glDisable(GL_LINE_STIPPLE)


    def pixels_for_upload(self, img_data):
        #prepare the pixel buffer for upload:
        t = type(img_data)
        if t==memoryview:
            if not zerocopy_upload:
                #not safe, make a copy :(
                return "copy:memoryview.tobytes", img_data.tobytes()
            return "zerocopy:memoryview", img_data
        elif t in (bytes, buffer_type) and zerocopy_upload:
            #we can zerocopy if we wrap it:
            return "zerocopy:buffer-as-memoryview", memoryview(img_data)
        elif t==bytes:
            return "copy:bytes", img_data
        else:
            if hasattr(img_data, "raw"):
                return "zerocopy:mmap", img_data.raw
            #everything else.. copy to bytes (aka str):
            return "copy:bytes(%s)" % t, strtobytes(img_data)

    def set_alignment(self, width, rowstride, pixel_format):
        bytes_per_pixel = len(pixel_format)       #ie: BGRX -> 4
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
        if (rowstride - width * bytes_per_pixel) >= alignment:
            row_length = width + (rowstride - width * bytes_per_pixel) // bytes_per_pixel
        glPixelStorei(GL_UNPACK_ROW_LENGTH, row_length)
        glPixelStorei(GL_UNPACK_ALIGNMENT, alignment)
        self.gl_marker("set_alignment%s GL_UNPACK_ROW_LENGTH=%i, GL_UNPACK_ALIGNMENT=%i", (width, rowstride, pixel_format), row_length, alignment)


    def paint_jpeg(self, img_data, x, y, width, height, options, callbacks):
        #img = self.jpeg_decoder.decompress_to_yuv(img_data, width, height, options)
        #self.idle_add(self.gl_paint_planar, flush, "jpeg", img, x, y, width, height, width, height, callbacks)
        img = self.jpeg_decoder.decompress_to_rgb("BGRX", img_data, width, height, options)
        self.idle_add(self.do_paint_rgb, "BGRX", img.get_pixels(), x, y, width, height, img.get_rowstride(), options, callbacks)


    def do_paint_rgb(self, rgb_format, img_data, x, y, width, height, rowstride, options, callbacks):
        log("%s.do_paint_rgb(%s, %s bytes, x=%d, y=%d, width=%d, height=%d, rowstride=%d, options=%s)", self, rgb_format, len(img_data), x, y, width, height, rowstride, options)
        context = self.gl_context()
        if not context:
            log("%s._do_paint_rgb(..) no context!", self)
            fire_paint_callbacks(callbacks, False, "no opengl context")
            return
        if not options.get("paint", True):
            fire_paint_callbacks(callbacks)
            return
        try:
            rgb_format = rgb_format.decode()
        except:
            pass
        try:
            upload, img_data = self.pixels_for_upload(img_data)

            with context:
                self.gl_init()

                #convert it to a GL constant:
                pformat = PIXEL_FORMAT_TO_CONSTANT.get(rgb_format)
                assert pformat is not None, "could not find pixel format for %s" % rgb_format
                ptype = PIXEL_FORMAT_TO_DATATYPE.get(rgb_format)
                assert pformat is not None, "could not find pixel type for %s" % rgb_format

                self.gl_marker("%s update at (%d,%d) size %dx%d (%s bytes), using GL %s format=%s / %s to internal format=%s",
                               rgb_format, x, y, width, height, len(img_data), upload, CONSTANT_TO_PIXEL_FORMAT.get(pformat), DATATYPE_TO_STR.get(ptype), INTERNAL_FORMAT_TO_STR.get(self.internal_format))

                # Upload data as temporary RGB texture
                target = GL_TEXTURE_RECTANGLE_ARB
                glEnable(target)
                glBindTexture(target, self.textures[TEX_RGB])
                self.set_alignment(width, rowstride, rgb_format)
                glTexParameteri(target, GL_TEXTURE_MAG_FILTER, GL_NEAREST)
                glTexParameteri(target, GL_TEXTURE_MIN_FILTER, GL_NEAREST)
                set_texture_level(target)
                glTexParameteri(target, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_BORDER)
                glTexParameteri(target, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_BORDER)
                glTexImage2D(target, 0, self.internal_format, width, height, 0, pformat, ptype, img_data)

                # Draw textured RGB quad at the right coordinates
                glBegin(GL_QUADS)
                glTexCoord2i(0, 0);             glVertex2i(x, y)
                glTexCoord2i(0, height);        glVertex2i(x, y+height)
                glTexCoord2i(width, height);    glVertex2i(x+width, y+height)
                glTexCoord2i(width, 0);         glVertex2i(x+width, y)
                glEnd()

                glBindTexture(target, 0)
                glDisable(target)
                self.paint_box(options.get("encoding"), options.get("delta", -1)>=0, x, y, width, height)

                # Present update to screen
                self.present_fbo(x, y, width, height, options.get("flush", 0))
                # present_fbo has reset state already
            fire_paint_callbacks(callbacks)
            return
        except GLError as e:
            message = "OpenGL %s paint failed: %r" % (rgb_format, e)
        except Exception as e:
            message = "OpenGL %s paint error: %s" % (rgb_format, e)
        log("Error in %s paint of %i bytes, options=%s", rgb_format, len(img_data), options, exc_info=True)
        fire_paint_callbacks(callbacks, False, message)

    def do_video_paint(self, img, x, y, enc_width, enc_height, width, height, options, callbacks):
        #copy so the data will be usable (usually a str)
        img.clone_pixel_data()
        self.idle_add(self.gl_paint_planar, options.get("flush", 0), options.get("encoding"), img, x, y, enc_width, enc_height, width, height, callbacks)

    def gl_paint_planar(self, flush, encoding, img, x, y, enc_width, enc_height, width, height, callbacks):
        #this function runs in the UI thread, no video_decoder lock held
        log("gl_paint_planar%s", (flush, encoding, img, x, y, enc_width, enc_height, width, height, callbacks))
        try:
            pixel_format = img.get_pixel_format()
            assert pixel_format in ("YUV420P", "YUV422P", "YUV444P", "GBRP"), "sorry the GL backing does not handle pixel format '%s' yet!" % (pixel_format)

            context = self.gl_context()
            if not context:
                log("%s._do_paint_rgb(..) no context!", self)
                fire_paint_callbacks(callbacks, False, "failed to get a gl context")
                return
            with context:
                self.gl_init()
                self.update_planar_textures(x, y, enc_width, enc_height, img, pixel_format, scaling=(enc_width!=width or enc_height!=height))

                # Update FBO texture
                x_scale, y_scale = 1, 1
                if width!=enc_width or height!=enc_height:
                    x_scale = float(width)/enc_width
                    y_scale = float(height)/enc_height
                self.render_planar_update(x, y, enc_width, enc_height, x_scale, y_scale)
                self.paint_box(encoding, False, x, y, width, height)
                # Present it on screen
                self.present_fbo(x, y, width, height, flush)
            img.free()
            fire_paint_callbacks(callbacks, True)
            return
        except GLError as e:
            message = "OpenGL %s paint failed: %r" % (encoding, e)
        except Exception as e:
            message = "OpenGL %s paint failed: %s" % (encoding, e)
        log.error("Error: %s", e, exc_info=True)
        log.error(" flush=%i, image=%s, coords=%s, size=%ix%i", flush, img, (x, y, enc_width, enc_height), width, height)
        fire_paint_callbacks(callbacks, False, message)

    def update_planar_textures(self, x, y, width, height, img, pixel_format, scaling=False):
        assert self.textures is not None, "no OpenGL textures!"
        log("%s.update_planar_textures%s", self, (x, y, width, height, img, pixel_format))

        divs = get_subsampling_divs(pixel_format)
        if self.pixel_format is None or self.pixel_format!=pixel_format or self.texture_size!=(width, height):
            self.pixel_format = pixel_format
            self.texture_size = (width, height)
            self.gl_marker("Creating new planar textures, pixel format %s", pixel_format)
            # Create textures of the same size as the window's

            for texture, index in ((GL_TEXTURE0, TEX_Y), (GL_TEXTURE1, TEX_U), (GL_TEXTURE2, TEX_V)):
                (div_w, div_h) = divs[index]
                glActiveTexture(texture)
                target = GL_TEXTURE_RECTANGLE_ARB
                glBindTexture(target, self.textures[index])
                mag_filter = GL_NEAREST
                if scaling or (div_w > 1 or div_h > 1):
                    mag_filter = GL_LINEAR
                glTexParameteri(target, GL_TEXTURE_MAG_FILTER, mag_filter)
                glTexParameteri(target, GL_TEXTURE_MIN_FILTER, GL_NEAREST)
                set_texture_level()
                glTexImage2D(target, 0, GL_LUMINANCE, width//div_w, height//div_h, 0, GL_LUMINANCE, GL_UNSIGNED_BYTE, None)
                #glBindTexture(target, 0)        #redundant: we rebind below:

        self.gl_marker("updating planar textures: %sx%s %s", width, height, pixel_format)
        rowstrides = img.get_rowstride()
        img_data = img.get_pixels()
        assert len(rowstrides)==3 and len(img_data)==3
        for texture, index in ((GL_TEXTURE0, TEX_Y), (GL_TEXTURE1, TEX_U), (GL_TEXTURE2, TEX_V)):
            (div_w, div_h) = divs[index]
            glActiveTexture(texture)

            target = GL_TEXTURE_RECTANGLE_ARB
            glBindTexture(target, self.textures[index])
            self.set_alignment(width//div_w, rowstrides[index], "YUV"[index])
            upload, pixel_data = self.pixels_for_upload(img_data[index])
            log("texture %s: div=%s, rowstride=%s, %sx%s, data=%s bytes, upload=%s", index, divs[index], rowstrides[index], width//div_w, height//div_h, len(pixel_data), upload)
            glTexParameteri(target, GL_TEXTURE_BASE_LEVEL, 0)
            try:
                glTexParameteri(target, GL_TEXTURE_MAX_LEVEL, 0)
            except:
                pass
            glTexSubImage2D(target, 0, 0, 0, width//div_w, height//div_h, GL_LUMINANCE, GL_UNSIGNED_BYTE, pixel_data)
            glBindTexture(target, 0)
        #glActiveTexture(GL_TEXTURE0)    #redundant, we always call render_planar_update afterwards

    def render_planar_update(self, rx, ry, rw, rh, x_scale=1, y_scale=1):
        log("%s.render_planar_update%s pixel_format=%s", self, (rx, ry, rw, rh, x_scale, y_scale), self.pixel_format)
        if self.pixel_format not in ("YUV420P", "YUV422P", "YUV444P", "GBRP"):
            #not ready to render yet
            return
        if self.pixel_format == "GBRP":
            # Set GL state for planar RGB: change fragment program
            glBindProgramARB(GL_FRAGMENT_PROGRAM_ARB, self.shaders[RGBP2RGB_SHADER])
        self.gl_marker("painting planar update, format %s", self.pixel_format)
        divs = get_subsampling_divs(self.pixel_format)
        glEnable(GL_FRAGMENT_PROGRAM_ARB)
        for texture, index in ((GL_TEXTURE0, TEX_Y), (GL_TEXTURE1, TEX_U), (GL_TEXTURE2, TEX_V)):
            glActiveTexture(texture)
            glBindTexture(GL_TEXTURE_RECTANGLE_ARB, self.textures[index])

        tw, th = self.texture_size
        log("%s.render_planar_update(..) texture_size=%s, size=%s", self, self.texture_size, self.size)
        glBegin(GL_QUADS)
        for x,y in ((0, 0), (0, rh), (rw, rh), (rw, 0)):
            ax = min(tw, x)
            ay = min(th, y)
            for texture, index in ((GL_TEXTURE0, TEX_Y), (GL_TEXTURE1, TEX_U), (GL_TEXTURE2, TEX_V)):
                (div_w, div_h) = divs[index]
                glMultiTexCoord2i(texture, ax//div_w, ay//div_h)
            glVertex2i(int(rx+ax*x_scale), int(ry+ay*y_scale))
        glEnd()
        for texture in (GL_TEXTURE0, GL_TEXTURE1, GL_TEXTURE2):
            glActiveTexture(texture)
            glBindTexture(GL_TEXTURE_RECTANGLE_ARB, 0)
        glDisable(GL_FRAGMENT_PROGRAM_ARB)
        if self.pixel_format == "GBRP":
            # Reset state to our default (YUV painting)
            glBindProgramARB(GL_FRAGMENT_PROGRAM_ARB, self.shaders[YUV2RGB_SHADER])
        glActiveTexture(GL_TEXTURE0)


    def gl_show(self, rect_count):
        start = monotonic_time()
        self.do_gl_show(rect_count)
        end = monotonic_time()
        flush_elapsed = end-self.last_flush
        self.last_flush = end
        fpslog("gl_show after %3ims took %2ims, %2i updates", flush_elapsed*1000, (end-start)*1000, rect_count)


    def gl_expose_rect(self, rect=None):
        if not self.paint_screen:
            return
        context = self.gl_context()
        if not context:
            return
        if not rect:
            w, h = self.size
            rect = (0, 0, w, h)
        with context:
            self.gl_init()
            self.present_fbo(*rect)
