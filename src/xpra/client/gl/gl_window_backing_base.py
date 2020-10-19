# This file is part of Xpra.
# Copyright (C) 2013 Serviware (Arthur Huillet, <ahuillet@serviware.com>)
# Copyright (C) 2012-2018 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import time
import struct
from ctypes import c_char_p

from OpenGL import version as OpenGL_version
from OpenGL.error import GLError
from OpenGL.GL import (
    GL_PROJECTION, GL_MODELVIEW,
    GL_UNPACK_ROW_LENGTH, GL_UNPACK_ALIGNMENT,
    GL_TEXTURE_MAG_FILTER, GL_TEXTURE_MIN_FILTER, GL_NEAREST,
    GL_UNSIGNED_BYTE, GL_LUMINANCE, GL_LINEAR,
    GL_TEXTURE0, GL_TEXTURE1, GL_TEXTURE2, GL_QUADS, GL_LINE_LOOP, GL_LINES, GL_COLOR_BUFFER_BIT,
    GL_TEXTURE_WRAP_S, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_BORDER,
    GL_DONT_CARE, GL_TRUE, GL_DEPTH_TEST, GL_SCISSOR_TEST, GL_LIGHTING, GL_DITHER,
    GL_RGB, GL_RGBA, GL_BGR, GL_BGRA, GL_RGBA8, GL_RGB8, GL_RGB10_A2, GL_RGB565, GL_RGB5_A1, GL_RGBA4,
    GL_UNSIGNED_INT_2_10_10_10_REV, GL_UNSIGNED_INT_10_10_10_2, GL_UNSIGNED_SHORT_5_6_5,
    GL_BLEND, GL_ONE, GL_ONE_MINUS_SRC_ALPHA, GL_SRC_ALPHA,
    GL_TEXTURE_MAX_LEVEL, GL_TEXTURE_BASE_LEVEL,
    GL_PERSPECTIVE_CORRECTION_HINT, GL_FASTEST,
    glLineStipple, GL_LINE_STIPPLE, GL_POINTS,
    glTexEnvi, GL_TEXTURE_ENV, GL_TEXTURE_ENV_MODE, GL_REPLACE,
    glHint,
    glBlendFunc,
    glActiveTexture, glTexSubImage2D,
    glGetString, glViewport, glMatrixMode, glLoadIdentity, glOrtho,
    glGenTextures, glDisable,
    glBindTexture, glPixelStorei, glEnable, glBegin, glFlush,
    glTexParameteri,
    glTexImage2D,
    glMultiTexCoord2i,
    glTexCoord2i, glVertex2i, glEnd,
    glClear, glClearColor, glLineWidth, glColor4f,
    glDrawBuffer, glReadBuffer,
    )
from OpenGL.GL.ARB.texture_rectangle import GL_TEXTURE_RECTANGLE_ARB
from OpenGL.GL.ARB.vertex_program import (
    glGenProgramsARB, glBindProgramARB, glProgramStringARB,
    GL_PROGRAM_ERROR_STRING_ARB, GL_PROGRAM_FORMAT_ASCII_ARB,
    )
from OpenGL.GL.ARB.fragment_program import GL_FRAGMENT_PROGRAM_ARB
from OpenGL.GL.ARB.framebuffer_object import (
    GL_FRAMEBUFFER, GL_DRAW_FRAMEBUFFER, GL_READ_FRAMEBUFFER,
    GL_COLOR_ATTACHMENT0, GL_COLOR_ATTACHMENT1, \
    glGenFramebuffers, glBindFramebuffer, glFramebufferTexture2D, glBlitFramebuffer,
    )

from xpra.os_util import (
    monotonic_time, strtobytes, hexstr,
    POSIX, PYTHON2, PYTHON3, OSX,
    DummyContextManager,
    )
from xpra.util import envint, envbool, repr_ellipsized
from xpra.client.paint_colors import get_paint_box_color
from xpra.codecs.codec_constants import get_subsampling_divs
from xpra.client.window_backing_base import (
    fire_paint_callbacks, WindowBackingBase,
    WEBP_PILLOW, SCROLL_ENCODING,
    )
from xpra.client.gl.gl_check import GL_ALPHA_SUPPORTED, is_pyopengl_memoryview_safe, get_max_texture_size
from xpra.client.gl.gl_colorspace_conversions import YUV2RGB_shader, YUV2RGB_FULL_shader, RGBP2RGB_shader
from xpra.client.gl.gl_spinner import draw_spinner
from xpra.log import Logger

log = Logger("opengl", "paint")
fpslog = Logger("opengl", "fps")

OPENGL_DEBUG = envbool("XPRA_OPENGL_DEBUG", False)
PAINT_FLUSH = envbool("XPRA_PAINT_FLUSH", True)
JPEG_YUV = envbool("XPRA_JPEG_YUV", True)
WEBP_YUV = envbool("XPRA_WEBP_YUV", True)
FORCE_CLONE = envbool("XPRA_OPENGL_FORCE_CLONE", False)
DRAW_REFRESH = envbool("XPRA_OPENGL_DRAW_REFRESH", True)
FBO_RESIZE = envbool("XPRA_OPENGL_FBO_RESIZE", True)
FBO_RESIZE_DELAY = envint("XPRA_OPENGL_FBO_RESIZE_DELAY", 50)
CONTEXT_REINIT = envbool("XPRA_OPENGL_CONTEXT_REINIT", False)

CURSOR_IDLE_TIMEOUT = envint("XPRA_CURSOR_IDLE_TIMEOUT", 6)
TEXTURE_CURSOR = envbool("XPRA_OPENGL_TEXTURE_CURSOR", True)

SAVE_BUFFERS = os.environ.get("XPRA_OPENGL_SAVE_BUFFERS")
if SAVE_BUFFERS not in ("png", "jpeg", None):
    log.warn("invalid value for XPRA_OPENGL_SAVE_BUFFERS: must be 'png' or 'jpeg'")
    SAVE_BUFFERS = None
if SAVE_BUFFERS:
    from OpenGL.GL import glGetTexImage     #pylint: disable=ungrouped-imports
    import numpy
    from PIL import Image, ImageOps


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
        from OpenGL.GL.KHR.debug import (
            GL_DEBUG_OUTPUT, GL_DEBUG_OUTPUT_SYNCHRONOUS,
            glDebugMessageControl, glDebugMessageCallback, glInitDebugKHR,
            )
    except ImportError:
        log("Unable to import GL_KHR_debug OpenGL extension. Debug output will be more limited.")
    try:
        from OpenGL.GL.GREMEDY.string_marker import glInitStringMarkerGREMEDY, glStringMarkerGREMEDY
        from OpenGL.GL.GREMEDY.frame_terminator import glInitFrameTerminatorGREMEDY, glFrameTerminatorGREMEDY
        from OpenGL.GL import GLDEBUGPROC #@UnresolvedImport
        def py_gl_debug_callback(source, error_type, error_id, severity, length, message, param):
            log.error("src %x type %x id %x severity %x length %d message %s, param=%s",
                      source, error_type, error_id, severity, length, message, param)
        gl_debug_callback = GLDEBUGPROC(py_gl_debug_callback)
    except ImportError:
        # This is normal- GREMEDY_string_marker is only available with OpenGL debuggers
        log("Unable to import GREMEDY OpenGL extension. Debug output will be more limited.")
    log("OpenGL debugging settings:")
    log(" GL_DEBUG_OUTPUT=%s, GL_DEBUG_OUTPUT_SYNCHRONOUS=%s", GL_DEBUG_OUTPUT, GL_DEBUG_OUTPUT_SYNCHRONOUS)
    log(" gl_debug_callback=%s", gl_debug_callback)
    log(" glInitStringMarkerGREMEDY=%s, glStringMarkerGREMEDY=%s",
        glInitStringMarkerGREMEDY, glStringMarkerGREMEDY)
    log(" glInitFrameTerminatorGREMEDY=%s, glFrameTerminatorGREMEDY=%s",
        glInitFrameTerminatorGREMEDY, glFrameTerminatorGREMEDY)

zerocopy_upload = False
if envbool("XPRA_ZEROCOPY_OPENGL_UPLOAD", True):
    try:
        import OpenGL_accelerate            #@UnresolvedImport
        assert OpenGL_accelerate
    except ImportError:
        pass
    else:
        zerocopy_upload = is_pyopengl_memoryview_safe(OpenGL_version.__version__, OpenGL_accelerate.__version__)


if POSIX:
    from xpra.gtk_common.error import xsync
    paint_context_manager = xsync
else:
    paint_context_manager = DummyContextManager()


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
YUV2RGB_FULL_SHADER = 2


"""
The logic is as follows:

We create an OpenGL framebuffer object, which will be always up-to-date with the latest windows contents.
This framebuffer object is updated with YUV painting and RGB painting. It is presented on screen by drawing a
textured quad when requested, that is: after each YUV or RGB painting operation, and upon receiving an expose event.
The use of a intermediate framebuffer object is the only way to guarantee that the client keeps
an always fully up-to-date window image, which is critical because of backbuffer content losses upon buffer swaps
or offscreen window movement.
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
        self.last_present_fbo_error = None

        WindowBackingBase.__init__(self, wid, window_alpha and self.HAS_ALPHA)
        self.init_gl_config(self._alpha_enabled)
        self.init_backing()
        self.bit_depth = self.get_bit_depth(pixel_depth)
        self.init_formats()
        self.draw_needs_refresh = DRAW_REFRESH
        #the correct check would be this:
        #self.repaint_all = self.is_double_buffered() or bw!=ww or bh!=wh
        #but we're meant to be using double-buffered everywhere, so don't bother:
        self.repaint_all = True
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
        log("init_formats() texture pixel format=%s, internal format=%s, rgb modes=%s",
            CONSTANT_TO_PIXEL_FORMAT.get(self.texture_pixel_format),
            INTERNAL_FORMAT_TO_STR.get(self.internal_format),
            self.RGB_MODES)

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
        self.render_size = ww, wh
        if self.size!=(bw, bh):
            self.gl_setup = False
            oldw, oldh = self.size
            self.size = bw, bh
            if CONTEXT_REINIT:
                self.close_gl_config()
                self.init_gl_config(self._alpha_enabled)
                return
            if FBO_RESIZE:
                self.resize_fbo(oldw, oldh, bw, bh)

    def resize_fbo(self, oldw, oldh, bw, bh):
        try:
            context = self.gl_context()
        except Exception:
            context = None
        if context is None or self.offscreen_fbo is None:
            return
        #if we have a valid context and an existing offscreen fbo,
        #preserve the existing pixels by copying them onto the new tmp fbo (new size)
        #and then doing the gl_init() call but without initializing the offscreen fbo.
        sx, sy, dx, dy, w, h = self.gravity_copy_coords(oldw, oldh, bw, bh)
        with context:
            context.update_geometry()
            #invert Y coordinates for OpenGL:
            sy = (oldh-h)-sy
            dy = (bh-h)-dy
            #re-init our OpenGL context with the new size,
            #but leave offscreen fbo with the old size
            self.gl_init(True)
            #copy offscreen to new tmp:
            self.copy_fbo(w, h, sx, sy, dx, dy)
            #make tmp the new offscreen:
            self.swap_fbos()
            #now we don't need the old tmp fbo contents any more,
            #and we can re-initialize it with the correct size:
            mag_filter = self.get_init_magfilter()
            self.init_fbo(TEX_TMP_FBO, self.tmp_fbo, bw, bh, mag_filter)
            #no idea why, but we have to wait a bit to show it:
            from xpra.gtk_common.gobject_compat import import_glib
            glib = import_glib()
        del context
        def redraw():
            context = self.gl_context()
            if not context:
                return
            with context:
                self.pending_fbo_paint = ((0, 0, bw, bh), )
                self.do_present_fbo()
        glib.timeout_add(FBO_RESIZE_DELAY, redraw)

    def gl_marker(self, *msg):
        log(*msg)
        if not bool(glStringMarkerGREMEDY):
            return
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
        if GL_DEBUG_OUTPUT and gl_debug_callback and glInitDebugKHR() is True:
            glEnable(GL_DEBUG_OUTPUT)
            glEnable(GL_DEBUG_OUTPUT_SYNCHRONOUS)
            glDebugMessageCallback(gl_debug_callback, None)
            glDebugMessageControl(GL_DONT_CARE, GL_DONT_CARE, GL_DONT_CARE, 0, None, GL_TRUE)
        # Initialize string_marker GL debugging extension if available
        if glInitStringMarkerGREMEDY and glInitStringMarkerGREMEDY() is True:
            log.info("Extension GL_GREMEDY_string_marker available. Will output detailed information about each frame.")
        else:
            # General case - running without debugger, extension not available
            glStringMarkerGREMEDY = None
            #don't bother trying again for another window:
            glInitStringMarkerGREMEDY = None
        # Initialize frame_terminator GL debugging extension if available
        if glInitFrameTerminatorGREMEDY and glInitFrameTerminatorGREMEDY() is True:
            log.info("Enabling GL frame terminator debugging.")
        else:
            glFrameTerminatorGREMEDY = None
            #don't bother trying again for another window:
            glInitFrameTerminatorGREMEDY = None

    def gl_init_textures(self):
        assert self.offscreen_fbo is None
        assert self.shaders is None
        assert glGenFramebuffers, "no framebuffer support"
        self.textures = glGenTextures(N_TEXTURES)
        self.offscreen_fbo = glGenFramebuffers(1)
        self.tmp_fbo = glGenFramebuffers(1)
        log("%s.gl_init_textures() textures: %s, offscreen fbo: %s, tmp fbo: %s",
            self, self.textures, self.offscreen_fbo, self.tmp_fbo)

    def gl_init_shaders(self):
        assert self.shaders is None
        # Create and assign fragment programs
        self.shaders = [ 1, 2, 3 ]
        glGenProgramsARB(3, self.shaders)
        for name, progid, progstr in (
            ("YUV2RGB",     YUV2RGB_SHADER,         YUV2RGB_shader),
            ("YUV2RGBFULL", YUV2RGB_FULL_SHADER,    YUV2RGB_FULL_shader),
            ("RGBP2RGB",    RGBP2RGB_SHADER,        RGBP2RGB_shader),
            ):
            glBindProgramARB(GL_FRAGMENT_PROGRAM_ARB, self.shaders[progid])
            glProgramStringARB(GL_FRAGMENT_PROGRAM_ARB, GL_PROGRAM_FORMAT_ASCII_ARB, len(progstr), progstr)
            err = glGetString(GL_PROGRAM_ERROR_STRING_ARB)
            if err:
                log.error("OpenGL shader %s failed:", name)
                log.error(" %s", err)
                raise Exception("OpenGL shader %s setup failure: %s" % (name, err))
            log("%s shader initialized", name)

    def gl_init(self, skip_fbo=False):
        #must be called within a context!
        #performs init if needed
        if not self.debug_setup:
            self.debug_setup = True
            self.gl_init_debug()

        if not self.gl_setup:
            mt = get_max_texture_size()
            w, h = self.size
            if w>mt or h>mt:
                raise Exception("invalid texture dimensions %ix%i, maximum is %i" % (w, h, mt))
            self.gl_marker("Initializing GL context for window size %s, backing size %s, max texture size=%i",
                           self.render_size, self.size, mt)
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

            mag_filter = self.get_init_magfilter()
            # Define empty tmp FBO
            self.init_fbo(TEX_TMP_FBO, self.tmp_fbo, w, h, mag_filter)
            if not skip_fbo:
                # Define empty FBO texture and set rendering to FBO
                self.init_fbo(TEX_FBO, self.offscreen_fbo, w, h, mag_filter)

            target = GL_TEXTURE_RECTANGLE_ARB
            glBindTexture(target, 0)

            # Create and assign fragment programs
            if not self.shaders:
                self.gl_init_shaders()

            # Bind program 0 for YUV painting by default
            glBindProgramARB(GL_FRAGMENT_PROGRAM_ARB, self.shaders[YUV2RGB_SHADER])
            self.gl_setup = True
            log("gl_init() done")

    def get_init_magfilter(self):
        rw, rh = self.render_size
        w, h = self.size
        if float(rw)/w!=rw//w or float(rh)/h!=rh//h:
            #non integer scaling, use linear magnification filter:
            return GL_LINEAR
        return GL_NEAREST


    def init_fbo(self, texture_index, fbo, w, h, mag_filter):
        target = GL_TEXTURE_RECTANGLE_ARB
        glBindTexture(target, self.textures[texture_index])
        # nvidia needs this even though we don't use mipmaps (repeated through this file):
        glTexParameteri(target, GL_TEXTURE_MAG_FILTER, mag_filter)
        glTexParameteri(target, GL_TEXTURE_MIN_FILTER, GL_NEAREST)
        glTexImage2D(target, 0, self.internal_format, w, h, 0, self.texture_pixel_format, GL_UNSIGNED_BYTE, None)
        glBindFramebuffer(GL_FRAMEBUFFER, fbo)
        glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, target, self.textures[texture_index], 0)
        self.gl_clear_color_buffer()

    def gl_clear_color_buffer(self):
        try:
            glClear(GL_COLOR_BUFFER_BIT)
        except Exception:
            log("ignoring glClear(GL_COLOR_BUFFER_BIT) error, buggy driver?", exc_info=True)


    def close_gl_config(self):
        pass

    def close(self):
        self.close_gl_config()
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


    def paint_scroll(self, scroll_data, options, callbacks):    #pylint: disable=arguments-differ
        flush = options.intget("flush", 0)
        self.idle_add(self.do_scroll_paints, scroll_data, flush, callbacks)

    def do_scroll_paints(self, scrolls, flush=0, callbacks=()):
        log("do_scroll_paints%s", (scrolls, flush))
        context = self.gl_context()
        if not context:
            log("%s.do_scroll_paints(..) no context!", self)
            fire_paint_callbacks(callbacks, False, "no opengl context")
            return
        def fail(msg):
            log.error("Error: %s", msg)
            fire_paint_callbacks(callbacks, False, msg)
        bw, bh = self.size
        with context:
            self.copy_fbo(bw, bh)

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
                    fail("horizontal scroll by %i:" % xdelta
                         +" rectangle %s overflows the backing buffer size %s" % ((x, y, w, h), self.size))
                    continue
                if y+ydelta<0:
                    fail("vertical scroll by %i:" % ydelta
                         +" rectangle %s overflows the backing buffer size %s" % ((x, y, w, h), self.size))
                    continue
                #opengl buffer is upside down, so we must invert Y coordinates: bh-(..)
                glBlitFramebuffer(x, bh-y, x+w, bh-(y+h),
                                  x+xdelta, bh-(y+ydelta), x+w+xdelta, bh-(y+h+ydelta),
                                  GL_COLOR_BUFFER_BIT, GL_NEAREST)
                self.paint_box("scroll", True, x+xdelta, y+ydelta, x+w+xdelta, y+h+ydelta)
                glFlush()

            self.swap_fbos()

            target = GL_TEXTURE_RECTANGLE_ARB
            #restore normal paint state:
            glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, target, self.textures[TEX_FBO], 0)
            glBindFramebuffer(GL_READ_FRAMEBUFFER, self.offscreen_fbo)
            glBindFramebuffer(GL_DRAW_FRAMEBUFFER, self.offscreen_fbo)
            glBindFramebuffer(GL_FRAMEBUFFER, self.offscreen_fbo)

            glBindTexture(target, 0)
            glDisable(target)
            fire_paint_callbacks(callbacks, True)
            if not self.draw_needs_refresh:
                self.present_fbo(0, 0, bw, bh, flush)

    def copy_fbo(self, w, h, sx=0, sy=0, dx=0, dy=0):
        #copy from offscreen to tmp:
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

        glBlitFramebuffer(sx, sy, sx+w, sy+h,
                          dx, dy, dx+w, dy+h,
                          GL_COLOR_BUFFER_BIT, GL_NEAREST)

    def swap_fbos(self):
        #swap references to tmp and offscreen so tmp becomes the new offscreen:
        tmp = self.offscreen_fbo
        self.offscreen_fbo = self.tmp_fbo
        self.tmp_fbo = tmp
        tmp = self.textures[TEX_FBO]
        self.textures[TEX_FBO] = self.textures[TEX_TMP_FBO]
        self.textures[TEX_TMP_FBO] = tmp


    def present_fbo(self, x, y, w, h, flush=0):
        log("present_fbo: adding %s to pending paint list (size=%i), flush=%s, paint_screen=%s",
            (x, y, w, h), len(self.pending_fbo_paint), flush, self.paint_screen)
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
                self.last_present_fbo_error = str(e)

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

        left, top, right, bottom = self.offsets

        #viewport for clearing the whole window:
        glViewport(0, 0, left+ww+right, top+wh+bottom)
        if self._alpha_enabled:
            # transparent background:
            glClearColor(0.0, 0.0, 0.0, 0.0)
        else:
            # black, no alpha:
            glClearColor(0.0, 0.0, 0.0, 1.0)
        if left or top or right or bottom:
            self.gl_clear_color_buffer()

        #from now on, take the offsets into account:
        glViewport(left, top, ww, wh)
        target = GL_TEXTURE_RECTANGLE_ARB
        if ww!=bw or wh!=bh:
            glTexParameteri(target, GL_TEXTURE_MAG_FILTER, GL_LINEAR)
            glTexParameteri(target, GL_TEXTURE_MIN_FILTER, GL_LINEAR)

        # Draw FBO texture on screen
        glEnable(target)      #redundant - done in rgb paint state
        glBindTexture(target, self.textures[TEX_FBO])
        if self._alpha_enabled:
            # support alpha channel if present:
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
        target = GL_TEXTURE_RECTANGLE_ARB
        bw, bh = self.size
        glEnable(target)
        glBindFramebuffer(GL_READ_FRAMEBUFFER, self.offscreen_fbo)
        glBindTexture(target, self.textures[TEX_FBO])
        glFramebufferTexture2D(GL_READ_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, target, self.textures[TEX_FBO], 0)
        glReadBuffer(GL_COLOR_ATTACHMENT0)
        glViewport(0, 0, bw, bh)
        size = bw*bh*4
        data = numpy.empty(size)
        img_data = glGetTexImage(target, 0, GL_BGRA, GL_UNSIGNED_BYTE, data)
        img = Image.frombuffer("RGBA", (bw, bh), img_data, "raw", "BGRA", bw*4)
        img = ImageOps.flip(img)
        kwargs = {}
        if not self._alpha_enabled or SAVE_BUFFERS=="jpeg":
            img = img.convert("RGB")
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
        glBindTexture(target, 0)
        glDisable(target)

    def draw_pointer(self):
        px, py, _, _, size, start_time = self.pointer_overlay
        elapsed = monotonic_time()-start_time
        log("pointer_overlay=%s, elapsed=%.1f, timeout=%s, cursor-data=%s",
            self.pointer_overlay, elapsed, CURSOR_IDLE_TIMEOUT, (self.cursor_data or [])[:7])
        if elapsed>=CURSOR_IDLE_TIMEOUT:
            #timeout - stop showing it:
            self.pointer_overlay = None
            return
        x = px
        y = py
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
        xhot = self.cursor_data[5]
        yhot = self.cursor_data[6]
        x = px-xhot
        y = py-yhot
        if TEXTURE_CURSOR:
            #paint the texture containing the cursor:
            glActiveTexture(GL_TEXTURE0)
            target = GL_TEXTURE_RECTANGLE_ARB
            glEnable(target)
            glBindTexture(target, self.textures[TEX_CURSOR])
            glEnable(GL_BLEND)
            glBlendFunc(GL_ONE, GL_ONE_MINUS_SRC_ALPHA)
            #glTexEnvi(GL_TEXTURE_ENV, GL_TEXTURE_ENV_MODE, GL_REPLACE)

            glBegin(GL_QUADS)
            glTexCoord2i(0, 0)
            glVertex2i(x, y)
            glTexCoord2i(0, ch)
            glVertex2i(x, y+ch)
            glTexCoord2i(cw, ch)
            glVertex2i(x+cw, y+ch)
            glTexCoord2i(cw, 0)
            glVertex2i(x+cw, y)
            glEnd()

            glDisable(GL_BLEND)
            glBindTexture(target, 0)
            glDisable(target)
        else:
            #ugly and slow: paint each pixel separately..
            if not self.validate_cursor():
                return
            pixels = self.cursor_data[8]
            blen = cw*ch*4
            p = struct.unpack(b"B"*blen, pixels)
            glLineWidth(1)
            for cx in range(cw):
                for cy in range(ch):
                    i = cx*4+cy*cw*4
                    if p[i+3]>=64:
                        glBegin(GL_POINTS)
                        glColor4f(p[i]/256.0, p[i+1]/256.0, p[i+2]/256.0, p[i+3]/256.0)
                        glVertex2i(x+cx, y+cy)
                        glEnd()

    def draw_spinner(self):
        bw, bh = self.size
        draw_spinner(bw, bh)

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


    def validate_cursor(self):
        cursor_data = self.cursor_data
        cw = cursor_data[3]
        ch = cursor_data[4]
        pixels = cursor_data[8]
        blen = cw*ch*4
        if len(pixels)!=blen:
            log.error("Error: invalid cursor pixel buffer for %ix%i", cw, ch)
            log.error(" expected %i bytes but got %i (%s)", blen, len(pixels), type(pixels))
            log.error(" %s", repr_ellipsized(hexstr(pixels)))
            return False
        return True

    def set_cursor_data(self, cursor_data):
        if (not cursor_data or len(cursor_data)==1) and self.default_cursor_data:
            cursor_data = ["raw"] + self.default_cursor_data
        if not cursor_data:
            return
        self.cursor_data = cursor_data
        if not cursor_data or not TEXTURE_CURSOR:
            return
        cw = cursor_data[3]
        ch = cursor_data[4]
        pixels = cursor_data[8]
        if not self.validate_cursor():
            return
        context = self.gl_context()
        if not context:
            return
        with context:
            self.gl_init()
            self.upload_cursor_texture(cw, ch, pixels)

    def upload_cursor_texture(self, width, height, pixels):
        upload, pixel_data = self.pixels_for_upload(pixels)
        rgb_format = "RGBA"
        glActiveTexture(GL_TEXTURE0)
        target = GL_TEXTURE_RECTANGLE_ARB
        glEnable(target)
        glBindTexture(target, self.textures[TEX_CURSOR])
        self.set_alignment(width, width*4, rgb_format)
        glTexParameteri(target, GL_TEXTURE_MAG_FILTER, GL_NEAREST)
        glTexParameteri(target, GL_TEXTURE_MIN_FILTER, GL_NEAREST)
        glTexParameteri(target, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_BORDER)
        glTexParameteri(target, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_BORDER)
        glTexImage2D(target, 0, GL_RGBA8, width, height, 0, GL_RGBA, GL_UNSIGNED_BYTE, pixel_data)
        log("GL cursor %ix%i uploaded %i bytes of %s pixel data using %s",
            width, height, len(pixels), rgb_format, upload)
        glBindTexture(target, 0)
        glDisable(target)

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
        if isinstance(img_data, memoryview):
            if not zerocopy_upload:
                #not safe, make a copy :(
                return "copy:memoryview.tobytes", img_data.tobytes()
            return "zerocopy:memoryview", img_data
        if isinstance(img_data, bytes) and zerocopy_upload:
            #we can zerocopy if we wrap it:
            return "zerocopy:bytes-as-memoryview", memoryview(img_data)
        if PYTHON2 and isinstance(img_data, buffer) and zerocopy_upload:    #@UndefinedVariable
            #we can zerocopy if we wrap it:
            return "zerocopy:buffer-as-memoryview", memoryview(img_data)
        if isinstance(img_data, bytes):
            return "copy:bytes", img_data
        if hasattr(img_data, "raw"):
            return "zerocopy:mmap", img_data.raw
        #everything else.. copy to bytes (aka str):
        return "copy:bytes(%s)" % type(img_data), strtobytes(img_data)

    def set_alignment(self, width, rowstride, pixel_format):
        bytes_per_pixel = len(pixel_format)       #ie: BGRX -> 4
        # Compute alignment and row length
        row_length = 0
        alignment = 1
        for a in (2, 4, 8):
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
        self.gl_marker("set_alignment%s GL_UNPACK_ROW_LENGTH=%i, GL_UNPACK_ALIGNMENT=%i",
                       (width, rowstride, pixel_format), row_length, alignment)


    def paint_jpeg(self, img_data, x, y, width, height, options, callbacks):
        if JPEG_YUV and width>=2 and height>=2:
            img = self.jpeg_decoder.decompress_to_yuv(img_data, width, height, options)
            flush = options.intget("flush", 0)
            self.idle_add(self.gl_paint_planar, YUV2RGB_FULL_SHADER, flush, "jpeg", img, x, y, width, height, width, height, callbacks)
        else:
            img = self.jpeg_decoder.decompress_to_rgb("BGRX", img_data, width, height, options)
            self.idle_add(self.do_paint_rgb, "BGRX", img.get_pixels(), x, y, width, height, img.get_rowstride(), options, callbacks)

    def paint_webp(self, img_data, x, y, width, height, options, callbacks):
        subsampling = options.strget("subsampling")
        has_alpha = options.boolget("has_alpha")
        if subsampling=="YUV420P" and WEBP_YUV and self.webp_decoder and not WEBP_PILLOW and not has_alpha and width>=2 and height>=2:
            img = self.webp_decoder.decompress_yuv(img_data)
            flush = options.intget("flush", 0)
            self.idle_add(self.gl_paint_planar, YUV2RGB_SHADER, flush, "webp", img, x, y, width, height, width, height, callbacks)
            return
        WindowBackingBase.paint_webp(self, img_data, x, y, width, height, options, callbacks)

    def do_paint_rgb(self, rgb_format, img_data, x, y, width, height, rowstride, options, callbacks):
        log("%s.do_paint_rgb(%s, %s bytes, x=%d, y=%d, width=%d, height=%d, rowstride=%d, options=%s)",
            self, rgb_format, len(img_data), x, y, width, height, rowstride, options)
        context = self.gl_context()
        if not context:
            log("%s._do_paint_rgb(..) no context!", self)
            fire_paint_callbacks(callbacks, False, "no opengl context")
            return
        if not options.boolget("paint", True):
            fire_paint_callbacks(callbacks)
            return
        try:
            rgb_format = rgb_format.decode("utf-8")
        except (AttributeError, UnicodeDecodeError):
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
                glTexParameteri(target, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_BORDER)
                glTexParameteri(target, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_BORDER)
                glTexImage2D(target, 0, self.internal_format, width, height, 0, pformat, ptype, img_data)

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

                glBindTexture(target, 0)
                glDisable(target)
                self.paint_box(options.strget("encoding"), options.intget("delta", -1)>=0, x, y, width, height)
                # Present update to screen
                if not self.draw_needs_refresh:
                    self.present_fbo(x, y, width, height, options.intget("flush", 0))
                # present_fbo has reset state already
            fire_paint_callbacks(callbacks)
            return
        except GLError as e:
            message = "OpenGL %s paint failed: %r" % (rgb_format, e)
            log("Error in %s paint of %i bytes, options=%s", rgb_format, len(img_data), options, exc_info=True)
        except Exception as e:
            message = "OpenGL %s paint error: %s" % (rgb_format, e)
            log("Error in %s paint of %i bytes, options=%s", rgb_format, len(img_data), options, exc_info=True)
        fire_paint_callbacks(callbacks, False, message)


    def do_video_paint(self, img, x, y, enc_width, enc_height, width, height, options, callbacks):
        if not zerocopy_upload or FORCE_CLONE:
            #copy so the data will be usable (usually a str)
            img.clone_pixel_data()
        pixel_format = img.get_pixel_format()
        if pixel_format=="GBRP":
            shader = RGBP2RGB_SHADER
        else:
            shader = YUV2RGB_SHADER
        self.idle_add(self.gl_paint_planar, shader, options.intget("flush", 0), options.strget("encoding"), img,
                      x, y, enc_width, enc_height, width, height, callbacks)

    def gl_paint_planar(self, shader, flush, encoding, img,
                        x, y, enc_width, enc_height, width, height, callbacks):
        #this function runs in the UI thread, no video_decoder lock held
        log("gl_paint_planar%s", (flush, encoding, img, x, y, enc_width, enc_height, width, height, callbacks))
        try:
            pixel_format = img.get_pixel_format()
            assert pixel_format in ("YUV420P", "YUV422P", "YUV444P", "GBRP"), \
                "sorry the GL backing does not handle pixel format '%s' yet!" % (pixel_format)

            context = self.gl_context()
            if not context:
                log("%s._do_paint_rgb(..) no context!", self)
                fire_paint_callbacks(callbacks, False, "failed to get a gl context")
                return
            with context:
                self.gl_init()
                scaling = enc_width!=width or enc_height!=height
                self.update_planar_textures(enc_width, enc_height, img, pixel_format, scaling=scaling)

                # Update FBO texture
                x_scale, y_scale = 1, 1
                if width!=enc_width or height!=enc_height:
                    x_scale = float(width)/enc_width
                    y_scale = float(height)/enc_height

                self.render_planar_update(x, y, enc_width, enc_height, x_scale, y_scale, shader)
                self.paint_box(encoding, False, x, y, width, height)
                fire_paint_callbacks(callbacks, True)
                # Present it on screen
                if not self.draw_needs_refresh:
                    self.present_fbo(x, y, width, height, flush)
            img.free()
            return
        except GLError as e:
            message = "OpenGL %s paint failed: %r" % (encoding, e)
            log.error("Error painting planar update", exc_info=True)
        except Exception as e:
            message = "OpenGL %s paint failed: %s" % (encoding, e)
            log.error("Error painting planar update", exc_info=True)
        log.error(" flush=%i, image=%s, coords=%s, size=%ix%i",
                  flush, img, (x, y, enc_width, enc_height), width, height)
        fire_paint_callbacks(callbacks, False, message)

    def update_planar_textures(self, width, height, img, pixel_format, scaling=False):
        assert self.textures is not None, "no OpenGL textures!"
        log("%s.update_planar_textures%s", self, (width, height, img, pixel_format))

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
                glTexImage2D(target, 0, GL_LUMINANCE, width//div_w, height//div_h, 0, GL_LUMINANCE, GL_UNSIGNED_BYTE, None)
                #glBindTexture(target, 0)        #redundant: we rebind below:

        self.gl_marker("updating planar textures: %sx%s %s", width, height, pixel_format)
        rowstrides = img.get_rowstride()
        img_data = img.get_pixels()
        assert len(rowstrides)==3 and len(img_data)==3
        for texture, index, tex_name in (
            (GL_TEXTURE0, TEX_Y, "Y"),
            (GL_TEXTURE1, TEX_U, "U"),
            (GL_TEXTURE2, TEX_V, "V"),
            ):
            div_w, div_h = divs[index]
            w = width//div_w
            h = height//div_h
            if w==0 or h==0:
                log.error("Error: zero dimension %ix%i for %s planar texture %s", w, h, pixel_format, tex_name)
                log.error(" screen update %s dropped", (width, height))
                continue
            glActiveTexture(texture)

            target = GL_TEXTURE_RECTANGLE_ARB
            glBindTexture(target, self.textures[index])
            self.set_alignment(w, rowstrides[index], tex_name)
            upload, pixel_data = self.pixels_for_upload(img_data[index])
            log("texture %s: div=%s, rowstride=%s, %sx%s, data=%s bytes, upload=%s",
                index, divs[index], rowstrides[index], w, h, len(pixel_data), upload)
            glTexParameteri(target, GL_TEXTURE_BASE_LEVEL, 0)
            try:
                glTexParameteri(target, GL_TEXTURE_MAX_LEVEL, 0)
            except Exception:
                pass
            glTexSubImage2D(target, 0, 0, 0, w, h, GL_LUMINANCE, GL_UNSIGNED_BYTE, pixel_data)
            glBindTexture(target, 0)
        #glActiveTexture(GL_TEXTURE0)    #redundant, we always call render_planar_update afterwards

    def render_planar_update(self, rx, ry, rw, rh, x_scale=1, y_scale=1, shader=YUV2RGB_SHADER):
        log("%s.render_planar_update%s pixel_format=%s",
            self, (rx, ry, rw, rh, x_scale, y_scale, shader), self.pixel_format)
        if self.pixel_format not in ("YUV420P", "YUV422P", "YUV444P", "GBRP"):
            #not ready to render yet
            return
        glBindProgramARB(GL_FRAGMENT_PROGRAM_ARB, self.shaders[shader])
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
