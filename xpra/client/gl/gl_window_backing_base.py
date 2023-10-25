# This file is part of Xpra.
# Copyright (C) 2013 Serviware (Arthur Huillet, <ahuillet@serviware.com>)
# Copyright (C) 2012-2023 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import time
from time import monotonic
from typing import Dict, Tuple, Any, Optional, Callable, Iterable, List
from contextlib import AbstractContextManager
from gi.repository import GLib  # @UnresolvedImport

from OpenGL import version as OpenGL_version
from OpenGL.error import GLError
from OpenGL.constant import IntConstant
from OpenGL.GL import (
    GL_PIXEL_UNPACK_BUFFER, GL_STREAM_DRAW,
    GL_PROJECTION, GL_MODELVIEW,
    GL_UNPACK_ROW_LENGTH, GL_UNPACK_ALIGNMENT,
    GL_TEXTURE_MAG_FILTER, GL_TEXTURE_MIN_FILTER, GL_NEAREST,
    GL_UNSIGNED_BYTE, GL_UNSIGNED_SHORT,
    GL_LINEAR, GL_RED, GL_R8, GL_R16, GL_LUMINANCE, GL_LUMINANCE_ALPHA,
    GL_TEXTURE0, GL_TEXTURE1, GL_TEXTURE2, GL_QUADS, GL_LINE_LOOP, GL_LINES, GL_COLOR_BUFFER_BIT,
    GL_TEXTURE_WRAP_S, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_BORDER,
    GL_DONT_CARE, GL_TRUE, GL_DEPTH_TEST, GL_SCISSOR_TEST, GL_LIGHTING, GL_DITHER,
    GL_RGB, GL_RGBA, GL_BGR, GL_BGRA, GL_RGBA8, GL_RGB8, GL_RGB10_A2, GL_RGB565, GL_RGB5_A1, GL_RGBA4, GL_RGBA16,
    GL_UNSIGNED_INT_2_10_10_10_REV, GL_UNSIGNED_INT_10_10_10_2, GL_UNSIGNED_SHORT_5_6_5,
    GL_BLEND, GL_ONE, GL_ONE_MINUS_SRC_ALPHA, GL_SRC_ALPHA,
    GL_TEXTURE_MAX_LEVEL, GL_TEXTURE_BASE_LEVEL,
    GL_PERSPECTIVE_CORRECTION_HINT, GL_FASTEST,
    glTexEnvi, GL_TEXTURE_ENV, GL_TEXTURE_ENV_MODE, GL_REPLACE,
    glHint,
    glBlendFunc,
    glActiveTexture, glTexSubImage2D,
    glGetString, glViewport, glMatrixMode, glLoadIdentity, glOrtho,
    glGenTextures, glDisable,
    glBindTexture, glPixelStorei, glEnable, glBegin, glFlush,
    glBindBuffer, glGenBuffers, glBufferData, glDeleteBuffers,
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
    strtobytes, bytestostr, hexstr,
    POSIX, OSX,
    DummyContextManager,
    )
from xpra.util import envint, envbool, repr_ellipsized, first_time, roundup
from xpra.common import noop
from xpra.codecs.codec_constants import get_subsampling_divs, get_plane_name
from xpra.client.gui.window_border import WindowBorder
from xpra.client.gui.paint_colors import get_paint_box_color
from xpra.client.gui.window_backing_base import (
    fire_paint_callbacks, WindowBackingBase,
    WEBP_PILLOW, SCROLL_ENCODING,
    )
from xpra.client.gl.gl_check import GL_ALPHA_SUPPORTED, get_max_texture_size
from xpra.client.gl.gl_colorspace_conversions import (
    YUV_to_RGB_shader, YUV_to_RGB_FULL_shader, RGBP_to_RGB_shader, NV12_to_RGB_shader,
    )
from xpra.client.gl.gl_spinner import draw_spinner
from xpra.log import Logger

log = Logger("opengl", "paint")
fpslog = Logger("opengl", "fps")

OPENGL_DEBUG : bool = envbool("XPRA_OPENGL_DEBUG", False)
PAINT_FLUSH : bool = envbool("XPRA_PAINT_FLUSH", True)
JPEG_YUV : bool = envbool("XPRA_JPEG_YUV", True)
WEBP_YUV : bool = envbool("XPRA_WEBP_YUV", True)
FORCE_CLONE : bool = envbool("XPRA_OPENGL_FORCE_CLONE", False)
FORCE_VIDEO_PIXEL_FORMAT : str = os.environ.get("XPRA_FORCE_VIDEO_PIXEL_FORMAT", "")
DRAW_REFRESH : bool = envbool("XPRA_OPENGL_DRAW_REFRESH", True)
FBO_RESIZE : bool = envbool("XPRA_OPENGL_FBO_RESIZE", True)
FBO_RESIZE_DELAY : int = envint("XPRA_OPENGL_FBO_RESIZE_DELAY", -1)
CONTEXT_REINIT : bool = envbool("XPRA_OPENGL_CONTEXT_REINIT", False)
NVJPEG : bool = envbool("XPRA_OPENGL_NVJPEG", True)
NVDEC : bool = envbool("XPRA_OPENGL_NVDEC", True)

CURSOR_IDLE_TIMEOUT : int = envint("XPRA_CURSOR_IDLE_TIMEOUT", 6)

SAVE_BUFFERS : str = os.environ.get("XPRA_OPENGL_SAVE_BUFFERS", "")
if SAVE_BUFFERS not in ("png", "jpeg", ""):
    log.warn("invalid value for XPRA_OPENGL_SAVE_BUFFERS: must be 'png' or 'jpeg'")
    SAVE_BUFFERS = ""
if SAVE_BUFFERS:
    from OpenGL.GL import glGetTexImage     #pylint: disable=ungrouped-imports
    from PIL import Image, ImageOps         # @UnresolvedImport


PIXEL_FORMAT_TO_CONSTANT : Dict[str,IntConstant] = {
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
PIXEL_INTERNAL_FORMAT : Dict[str,Tuple[IntConstant,...]] = {
    #defaults to: GL_R8, GL_R8, GL_R8
    #(meaning: 3 planes, 8 bits each)
    #override for formats that use 16 bit per channel:
    "NV12" : (GL_LUMINANCE, GL_LUMINANCE_ALPHA),
    "GBRP" : (GL_LUMINANCE, GL_LUMINANCE, GL_LUMINANCE),    #invalid according to the spec! (only value that works)
    "GBRP16" : (GL_R16, GL_R16, GL_R16),
    "YUV444P10" : (GL_R16, GL_R16, GL_R16),
    "YUV444P16" : (GL_R16, GL_R16, GL_R16),
    }
PIXEL_DATA_FORMAT : Dict[str,Tuple[IntConstant,...]] = {
    #defaults to: (GL_RED, GL_RED, GL_RED))
    #(meaning: uploading one channel at a time)
    "NV12"  : (GL_LUMINANCE, GL_LUMINANCE_ALPHA),  #Y is one channel, UV contains two channels
    }
PIXEL_UPLOAD_FORMAT : Dict[str,Any] = {
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
    #planar formats:
    "NV12"  : (GL_UNSIGNED_BYTE, GL_UNSIGNED_BYTE),
    "YUV420P" : (GL_UNSIGNED_BYTE, GL_UNSIGNED_BYTE, GL_UNSIGNED_BYTE),
    "YUV422P" : (GL_UNSIGNED_BYTE, GL_UNSIGNED_BYTE, GL_UNSIGNED_BYTE),
    "YUV444P" : (GL_UNSIGNED_BYTE, GL_UNSIGNED_BYTE, GL_UNSIGNED_BYTE),
    "GBRP"  : (GL_UNSIGNED_BYTE, GL_UNSIGNED_BYTE, GL_UNSIGNED_BYTE),
    "GBRP16" : (GL_UNSIGNED_SHORT, GL_UNSIGNED_SHORT, GL_UNSIGNED_SHORT),
    "YUV444P10" : (GL_UNSIGNED_SHORT, GL_UNSIGNED_SHORT, GL_UNSIGNED_SHORT),
    "YUV444P16" : (GL_UNSIGNED_SHORT, GL_UNSIGNED_SHORT, GL_UNSIGNED_SHORT),
    }
CONSTANT_TO_PIXEL_FORMAT : Dict[IntConstant,str] = {
    GL_BGR   : "BGR",
    GL_RGB   : "RGB",
    GL_BGRA  : "BGRA",
    GL_RGBA  : "RGBA",
    }
INTERNAL_FORMAT_TO_STR : Dict[IntConstant,str] = {
    GL_RGB10_A2     : "RGB10_A2",
    GL_RGBA8        : "RGBA8",
    GL_RGB8         : "RGB8",
    GL_RGB565       : "RGB565",
    GL_RGB5_A1      : "RGB5_A1",
    GL_RGBA4        : "RGBA4",
    GL_RGBA16       : "GL_RGBA16",
    }
DATATYPE_TO_STR : Dict[IntConstant,str] = {
    GL_UNSIGNED_INT_2_10_10_10_REV  : "UNSIGNED_INT_2_10_10_10_REV",
    GL_UNSIGNED_INT_10_10_10_2      : "UNSIGNED_INT_10_10_10_2",
    GL_UNSIGNED_BYTE                : "UNSIGNED_BYTE",
    GL_UNSIGNED_SHORT               : "UNSIGNED_SHORT",
    GL_UNSIGNED_SHORT_5_6_5         : "UNSIGNED_SHORT_5_6_5",
    }

#debugging variables:
GL_DEBUG_OUTPUT : int = 0
GL_DEBUG_OUTPUT_SYNCHRONOUS : int = 0
gl_debug_callback : Callable = noop
glInitStringMarkerGREMEDY : Callable = noop
glStringMarkerGREMEDY : Callable = noop
glInitFrameTerminatorGREMEDY : Callable = noop
glFrameTerminatorGREMEDY : Callable = noop
GREMEDY_DEBUG = OPENGL_DEBUG
KHR_DEBUG = OPENGL_DEBUG
if OPENGL_DEBUG:
    try:
        # pylint: disable=ungrouped-imports
        from OpenGL.GL.KHR import debug as KHR_debug
        GL_DEBUG_OUTPUT = int(KHR_debug.GL_DEBUG_OUTPUT)  # @UndefinedVariable
        GL_DEBUG_OUTPUT_SYNCHRONOUS = int(KHR_debug.GL_DEBUG_OUTPUT_SYNCHRONOUS)
        from OpenGL.GL.KHR.debug import (
            glDebugMessageControl, glDebugMessageCallback, glInitDebugKHR,
            )
    except ImportError:
        log("Unable to import GL_KHR_debug OpenGL extension. Debug output will be more limited.")
        KHR_DEBUG = False
    try:
        from OpenGL.GL.GREMEDY import string_marker, frame_terminator
        glInitStringMarkerGREMEDY = string_marker.glInitStringMarkerGREMEDY
        glStringMarkerGREMEDY = string_marker.glStringMarkerGREMEDY
        glInitFrameTerminatorGREMEDY = frame_terminator.glInitFrameTerminatorGREMEDY
        glFrameTerminatorGREMEDY = frame_terminator.glFrameTerminatorGREMEDY
        from OpenGL.GL import GLDEBUGPROC #@UnresolvedImport
        def py_gl_debug_callback(source, error_type, error_id, severity, length, message, param):
            log.error("src %x type %x id %x severity %x length %d message %s, param=%s",
                      source, error_type, error_id, severity, length, message, param)
        gl_debug_callback = GLDEBUGPROC(py_gl_debug_callback)
    except ImportError:
        # This is normal- GREMEDY_string_marker is only available with OpenGL debuggers
        GREMEDY_DEBUG = False
        log("Unable to import GREMEDY OpenGL extension. Debug output will be more limited.")
    log("OpenGL debugging settings:")
    log(" GL_DEBUG_OUTPUT=%s, GL_DEBUG_OUTPUT_SYNCHRONOUS=%s", GL_DEBUG_OUTPUT, GL_DEBUG_OUTPUT_SYNCHRONOUS)
    log(" gl_debug_callback=%s", gl_debug_callback)
    log(" glInitStringMarkerGREMEDY=%s, glStringMarkerGREMEDY=%s", glInitStringMarkerGREMEDY, glStringMarkerGREMEDY)
    log(" glInitFrameTerminatorGREMEDY=%s, glFrameTerminatorGREMEDY=%s", glInitFrameTerminatorGREMEDY, glFrameTerminatorGREMEDY)

zerocopy_upload : bool = False
if envbool("XPRA_ZEROCOPY_OPENGL_UPLOAD", True):
    try:
        import OpenGL_accelerate            #@UnresolvedImport
        assert OpenGL_accelerate
    except ImportError:
        pass
    else:
        zerocopy_upload = OpenGL_version.__version__==OpenGL_accelerate.__version__

paint_context_manager: AbstractContextManager = DummyContextManager()
if POSIX and not OSX:
    # pylint: disable=ungrouped-imports
    from xpra.gtk_common.error import xsync
    paint_context_manager = xsync


# Texture number assignment
# The first four are used to update the FBO,
# the FBO is what is painted on screen.
TEX_Y = 0
TEX_U = 1
TEX_V = 2
TEX_RGB = 3
TEX_FBO = 4         #FBO texture (guaranteed up-to-date window contents)
TEX_TMP_FBO = 5
TEX_CURSOR = 6
TEX_FPS = 7
N_TEXTURES = 8

# Shader number assignment
YUV_to_RGB_SHADER = 0
RGBP_to_RGB_SHADER = 1
YUV_to_RGB_FULL_SHADER = 2
NV12_to_RGB_SHADER = 3


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

    RGB_MODES : List[str] = ["YUV420P", "YUV422P", "YUV444P", "GBRP", "BGRA", "BGRX", "RGBA", "RGBX", "RGB", "BGR", "NV12"]
    HAS_ALPHA : bool = GL_ALPHA_SUPPORTED

    def __init__(self, wid : int, window_alpha : bool, pixel_depth : int=0):
        self.wid : int = wid
        self.texture_pixel_format : Optional[IntConstant] = None
        #this is the pixel format we are currently updating the fbo with
        #can be: "YUV420P", "YUV422P", "YUV444P", "GBRP" or None when not initialized yet.
        self.pixel_format : str = ""
        self.textures = None # OpenGL texture IDs
        self.shaders = None
        self.texture_size : Tuple[int,int] = (0, 0)
        self.gl_setup : bool = False
        self.debug_setup : bool = False
        self.border : WindowBorder = WindowBorder(shown=False)
        self.paint_screen : bool = False
        self.paint_spinner : bool = False
        self.offscreen_fbo = None
        self.tmp_fbo = None
        self.pending_fbo_paint = []
        self.last_flush : float = monotonic()
        self.last_present_fbo_error : str = ""

        super().__init__(wid, window_alpha and self.HAS_ALPHA)
        self.init_gl_config()
        self.init_backing()
        self.bit_depth : int = self.get_bit_depth(pixel_depth)
        self.init_formats()
        self.draw_needs_refresh : bool = DRAW_REFRESH
        # the correct check would be this:
        # `self.repaint_all = self.is_double_buffered() or bw!=ww or bh!=wh`
        # but we're meant to be using double-buffered everywhere,
        # so don't bother and just repaint everything:
        self.repaint_all : bool = True
        self._backing.show()

    def get_info(self) -> Dict[str,Any]:
        info = super().get_info()
        tpf = self.texture_pixel_format
        tif = self.internal_format
        info.update({
            "type"                  : "OpenGL",
            "bit-depth"             : self.bit_depth,
            "pixel-format"          : self.pixel_format,
            "texture-pixel-format"  : CONSTANT_TO_PIXEL_FORMAT.get(tpf) or str(tpf),
            "internal-format"       : INTERNAL_FORMAT_TO_STR.get(tif) or str(tif),
            })
        return info


    def with_gl_context(self, cb:Callable, *args):
        raise NotImplementedError()

    def init_gl_config(self) -> None:
        raise NotImplementedError()

    def init_backing(self) -> None:
        raise NotImplementedError()

    def gl_context(self):
        raise NotImplementedError()

    def do_gl_show(self, rect_count) -> None:
        raise NotImplementedError()

    def is_double_buffered(self) -> bool:
        raise NotImplementedError()


    def get_bit_depth(self, pixel_depth:int=0) -> int:
        return pixel_depth or 24

    def init_formats(self) -> None:
        self.RGB_MODES = list(GLWindowBackingBase.RGB_MODES)
        if self.bit_depth>32:
            self.internal_format : int = GL_RGBA16
            self.RGB_MODES.append("r210")
            #self.RGB_MODES.append("GBRP16")
        elif self.bit_depth==30:
            self.internal_format = GL_RGB10_A2
            self.RGB_MODES.append("r210")
            #self.RGB_MODES.append("GBRP16")
        elif 0<self.bit_depth<=16:
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
            if self.bit_depth not in (0, 24, 32) and first_time(f"bit-depth-{self.bit_depth}"):
                log.warn(f"Warning: invalid bit depth {self.bit_depth}, using 24")
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

    def get_encoding_properties(self) -> Dict[str,Any]:
        props = super().get_encoding_properties()
        if SCROLL_ENCODING:
            props["encoding.scrolling"] = True
        props["encoding.bit-depth"] = self.bit_depth
        return props


    def __repr__(self):
        return f"GLWindowBacking({self.wid}, {self.size}, {self.pixel_format})"

    def init(self, ww : int, wh : int, bw : int, bh : int) -> None:
        #re-init gl projection with new dimensions
        #(see gl_init)
        self.render_size = ww, wh
        if self.size!=(bw, bh):
            self.cancel_fps_refresh()
            self.gl_setup = False
            oldw, oldh = self.size
            self.size = bw, bh
            if CONTEXT_REINIT:
                self.close_gl_config()
                self.init_gl_config()
                return
            if FBO_RESIZE:
                self.with_gl_context(self.resize_fbo, oldw, oldh, bw, bh)

    def resize_fbo(self, context, oldw : int, oldh : int, bw : int, bh : int) -> None:
        log("resize_fbo%s offscreen_fbo=%s",
            (context, oldw, oldh, bw, bh), self.offscreen_fbo)
        if not context or self.offscreen_fbo is None:
            return
        #if we have a valid context and an existing offscreen fbo,
        #preserve the existing pixels by copying them onto the new tmp fbo (new size)
        #and then doing the gl_init() call but without initializing the offscreen fbo.
        sx, sy, dx, dy, w, h = self.gravity_copy_coords(oldw, oldh, bw, bh)
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
        # now we don't need the old tmp fbo contents anymore,
        # and we can re-initialize it with the correct size:
        mag_filter = self.get_init_magfilter()
        self.init_fbo(TEX_TMP_FBO, self.tmp_fbo, bw, bh, mag_filter)
        self._backing.queue_draw_area(0, 0, bw, bh)
        if FBO_RESIZE_DELAY>=0:
            def redraw(context):
                if not context:
                    return
                self.pending_fbo_paint = ((0, 0, bw, bh), )
                self.do_present_fbo()
            GLib.timeout_add(FBO_RESIZE_DELAY, self.with_gl_context, redraw)


    def gl_marker(self, *msg) -> None:
        log(*msg)
        if not GREMEDY_DEBUG:
            return
        try:
            s = strtobytes(msg[0] % msg[1:])
        except TypeError:
            s = strtobytes(msg)
        from ctypes import c_char_p  # pylint: disable=import-outside-toplevel
        c_string = c_char_p(s)
        glStringMarkerGREMEDY(0, c_string)

    def gl_frame_terminator(self) -> None:
        # Mark the end of the frame
        # This makes the debug output more readable especially when doing single-buffered rendering
        if not GREMEDY_DEBUG:
            return
        log("glFrameTerminatorGREMEDY()")
        glFrameTerminatorGREMEDY()

    def gl_init_debug(self) -> None:
        #ensure python knows which scope we're talking about:
        global GREMEDY_DEBUG, KHR_DEBUG
        # Ask GL to send us all debug messages
        if KHR_DEBUG:
            if GL_DEBUG_OUTPUT and gl_debug_callback and glInitDebugKHR() is True:
                glEnable(GL_DEBUG_OUTPUT)
                glEnable(GL_DEBUG_OUTPUT_SYNCHRONOUS)
                glDebugMessageCallback(gl_debug_callback, None)
                glDebugMessageControl(GL_DONT_CARE, GL_DONT_CARE, GL_DONT_CARE, 0, None, GL_TRUE)
            else:
                KHR_DEBUG = False
        # Initialize string_marker GL debugging extension if available
        if GREMEDY_DEBUG:
            if glInitStringMarkerGREMEDY and glInitStringMarkerGREMEDY() is True:
                log.info("Extension GL_GREMEDY_string_marker available.")
                log.info(" Will output detailed information about each frame.")
            else:
                # General case - running without debugger, extension not available
                #don't bother trying again for another window:
                GREMEDY_DEBUG = False
            # Initialize frame_terminator GL debugging extension if available
            if glInitFrameTerminatorGREMEDY and glInitFrameTerminatorGREMEDY() is True:
                log.info("Enabling GL frame terminator debugging.")

    def gl_init_textures(self) -> None:
        assert self.offscreen_fbo is None
        assert self.shaders is None
        assert glGenFramebuffers, "no framebuffer support"
        self.textures = glGenTextures(N_TEXTURES)
        self.offscreen_fbo = glGenFramebuffers(1)
        self.tmp_fbo = glGenFramebuffers(1)
        log("%s.gl_init_textures() textures: %s, offscreen fbo: %s, tmp fbo: %s",
            self, self.textures, self.offscreen_fbo, self.tmp_fbo)

    def gl_init_shaders(self) -> None:
        assert self.shaders is None
        # Create and assign fragment programs
        self.shaders = [ 1, 2, 3, 4 ]
        glGenProgramsARB(4, self.shaders)
        for name, progid, progstr in (
            ("YUV_to_RGB",      YUV_to_RGB_SHADER,      YUV_to_RGB_shader),
            ("YUV_to_RGBFULL",  YUV_to_RGB_FULL_SHADER, YUV_to_RGB_FULL_shader),
            ("RGBP_to_RGB",     RGBP_to_RGB_SHADER,     RGBP_to_RGB_shader),
            ("NV12_to_RGB",     NV12_to_RGB_SHADER,     NV12_to_RGB_shader),
            ):
            glBindProgramARB(GL_FRAGMENT_PROGRAM_ARB, self.shaders[progid])
            try:
                glProgramStringARB(GL_FRAGMENT_PROGRAM_ARB, GL_PROGRAM_FORMAT_ASCII_ARB, len(progstr), progstr)
            except Exception as e:
                err = glGetString(GL_PROGRAM_ERROR_STRING_ARB) or str(e)
            else:
                err = glGetString(GL_PROGRAM_ERROR_STRING_ARB)
            if err:
                log.error("OpenGL shader %s failed:", name)
                log.error(" %s", err)
                raise RuntimeError(f"OpenGL shader {name} setup failure: {err}")
            log("%s shader initialized", name)

    def gl_init(self, skip_fbo:bool=False) -> None:
        #must be called within a context!
        #performs init if needed
        if not self.debug_setup:
            self.debug_setup = True
            self.gl_init_debug()

        if self.gl_setup:
            return
        mt = get_max_texture_size()
        w, h = self.size
        if w>mt or h>mt:
            raise ValueError(f"invalid texture dimensions {w}x{h}, maximum size is {mt}x{mt}")
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
        glBindProgramARB(GL_FRAGMENT_PROGRAM_ARB, self.shaders[YUV_to_RGB_SHADER])
        self.gl_setup = True
        log("gl_init(%s) done", skip_fbo)

    def get_init_magfilter(self) -> IntConstant:
        rw, rh = self.render_size
        w, h = self.size
        if rw/w!=rw//w or rh/h!=rh//h:
            #non integer scaling, use linear magnification filter:
            return GL_LINEAR
        return GL_NEAREST


    def init_fbo(self, texture_index : int, fbo, w : int, h : int, mag_filter) -> None:
        target = GL_TEXTURE_RECTANGLE_ARB
        glBindTexture(target, self.textures[texture_index])
        # nvidia needs this even though we don't use mipmaps (repeated through this file):
        glTexParameteri(target, GL_TEXTURE_MAG_FILTER, mag_filter)
        glTexParameteri(target, GL_TEXTURE_MIN_FILTER, GL_NEAREST)
        glTexImage2D(target, 0, self.internal_format, w, h, 0, self.texture_pixel_format, GL_UNSIGNED_BYTE, None)
        glBindFramebuffer(GL_FRAMEBUFFER, fbo)
        glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, target, self.textures[texture_index], 0)
        self.gl_clear_color_buffer()

    def gl_clear_color_buffer(self) -> None:
        try:
            glClear(GL_COLOR_BUFFER_BIT)
        except Exception:
            log("ignoring glClear(GL_COLOR_BUFFER_BIT) error, buggy driver?", exc_info=True)


    def close_gl_config(self) -> None:
        """
        Subclasses may free up resources at this point.
        The GTK3 GL drawing area does.
        """

    def close(self) -> None:
        self.free_cuda_context()
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
        super().close()


    def paint_scroll(self, scroll_data, options, callbacks) -> None:    #pylint: disable=arguments-differ, arguments-renamed
        flush = options.intget("flush", 0)
        self.idle_add(self.with_gl_context, self.do_scroll_paints, scroll_data, flush, callbacks)

    def do_scroll_paints(self, context, scrolls, flush:int=0, callbacks:Iterable[Callable]=()) -> None:
        log("do_scroll_paints%s", (context, scrolls, flush))
        if not context:
            log("%s.do_scroll_paints(..) no context!", self)
            fire_paint_callbacks(callbacks, False, "no opengl context")
            return
        def fail(msg):
            log.error("Error: %s", msg)
            fire_paint_callbacks(callbacks, False, msg)
        bw, bh = self.size
        self.copy_fbo(bw, bh)

        for x,y,w,h,xdelta,ydelta in scrolls:
            if abs(xdelta)>=bw:
                fail(f"invalid xdelta value: {xdelta}, backing width is {bw}")
                continue
            if abs(ydelta)>=bh:
                fail(f"invalid ydelta value: {ydelta}, backing height is {bh}")
                continue
            if ydelta==0 and xdelta==0:
                fail("scroll has no delta!")
                continue
            if w<=0 or h<=0:
                fail(f"invalid scroll area size: {w}x{h}")
                continue
            # these should be errors,
            # but desktop-scaling can cause a mismatch between the backing size
            # and the real window size server-side... so we clamp the dimensions instead
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
                rect = (x, y, w, h)
                fail(f"horizontal scroll by {xdelta}"
                     +f" rectangle {rect} overflows the backing buffer size {self.size}")
                continue
            if y+ydelta<0:
                rect = (x, y, w, h)
                fail(f"vertical scroll by {ydelta}"
                     +f" rectangle {rect} overflows the backing buffer size {self.size}")
                continue
            #opengl buffer is upside down, so we must invert Y coordinates: bh-(..)
            glBlitFramebuffer(x, bh-y, x+w, bh-(y+h),
                              x+xdelta, bh-(y+ydelta), x+w+xdelta, bh-(y+h+ydelta),
                              GL_COLOR_BUFFER_BIT, GL_NEAREST)
            self.paint_box("scroll", x+xdelta, y+ydelta, x+w+xdelta, y+h+ydelta)
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

    def copy_fbo(self, w : int, h : int, sx : int=0, sy : int=0, dx : int=0, dy : int=0) -> None:
        log("copy_fbo%s", (w, h, sx, sy, dx, dy))
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

    def swap_fbos(self) -> None:
        log("swap_fbos()")
        #swap references to tmp and offscreen so tmp becomes the new offscreen:
        tmp = self.offscreen_fbo
        self.offscreen_fbo = self.tmp_fbo
        self.tmp_fbo = tmp
        tmp = self.textures[TEX_FBO]
        self.textures[TEX_FBO] = self.textures[TEX_TMP_FBO]
        self.textures[TEX_TMP_FBO] = tmp


    def present_fbo(self, x : int, y : int, w : int, h : int, flush=0) -> None:
        log("present_fbo: adding %s to pending paint list (size=%i), flush=%s, paint_screen=%s",
            (x, y, w, h), len(self.pending_fbo_paint), flush, self.paint_screen)
        self.pending_fbo_paint.append((x, y, w, h))
        if not self.paint_screen:
            return
        #flush>0 means we should wait for the final flush=0 paint
        if flush==0 or not PAINT_FLUSH:
            self.record_fps_event()
            self.managed_present_fbo()

    def managed_present_fbo(self) -> None:
        try:
            with paint_context_manager:
                self.do_present_fbo()
        except Exception as e:
            log.error("Error presenting FBO:")
            log.estr(e)
            log("Error presenting FBO", exc_info=True)
            self.last_present_fbo_error = str(e)

    def do_present_fbo(self) -> None:
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

        if SAVE_BUFFERS:
            self.save_FBO()

        self.gl_marker("presenting FBO on screen, rectangles=%s", rectangles)
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

        if self.is_show_fps():
            self.draw_fps()

        # Show the backbuffer on screen
        glFlush()
        self.gl_show(rect_count)
        self.gl_frame_terminator()

        #restore pbo viewport
        glViewport(0, 0, bw, bh)
        glTexParameteri(target, GL_TEXTURE_MAG_FILTER, GL_NEAREST)
        glTexParameteri(target, GL_TEXTURE_MIN_FILTER, GL_NEAREST)
        glBindFramebuffer(GL_FRAMEBUFFER, self.offscreen_fbo)
        log("%s.do_present_fbo() done", self)

    def save_FBO(self) -> None:
        target = GL_TEXTURE_RECTANGLE_ARB
        bw, bh = self.size
        glEnable(target)
        glBindFramebuffer(GL_READ_FRAMEBUFFER, self.offscreen_fbo)
        glBindTexture(target, self.textures[TEX_FBO])
        glFramebufferTexture2D(GL_READ_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, target, self.textures[TEX_FBO], 0)
        glReadBuffer(GL_COLOR_ATTACHMENT0)
        glViewport(0, 0, bw, bh)
        size = bw*bh*4
        from xpra.buffers.membuf import get_membuf  #@UnresolvedImport pylint: disable=import-outside-toplevel
        membuf = get_membuf(size)
        glGetTexImage(target, 0, GL_BGRA, GL_UNSIGNED_BYTE, membuf.get_mem_ptr())
        pixels = memoryview(membuf).tobytes()
        img = Image.frombuffer("RGBA", (bw, bh), pixels, "raw", "BGRA", bw*4)
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

    def draw_pointer(self) -> None:
        px, py, _, _, size, start_time = self.pointer_overlay
        elapsed = monotonic()-start_time
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

        w = self.cursor_data[3]
        h = self.cursor_data[4]
        xhot = self.cursor_data[5]
        yhot = self.cursor_data[6]
        x = px-xhot
        y = py-yhot
        self.blend_texture(self.textures[TEX_CURSOR], x, y, w, h)

    def blend_texture(self, texture, x, y, w, h) -> None:
        #paint this texture
        glActiveTexture(GL_TEXTURE0)
        target = GL_TEXTURE_RECTANGLE_ARB
        glEnable(target)
        glBindTexture(target, texture)
        glEnable(GL_BLEND)
        glBlendFunc(GL_ONE, GL_ONE_MINUS_SRC_ALPHA)
        #glTexEnvi(GL_TEXTURE_ENV, GL_TEXTURE_ENV_MODE, GL_REPLACE)

        glBegin(GL_QUADS)
        glTexCoord2i(0, 0)
        glVertex2i(x, y)
        glTexCoord2i(0, h)
        glVertex2i(x, y+h)
        glTexCoord2i(w, h)
        glVertex2i(x+w, y+h)
        glTexCoord2i(w, 0)
        glVertex2i(x+w, y)
        glEnd()

        glDisable(GL_BLEND)
        glBindTexture(target, 0)
        glDisable(target)

    def draw_spinner(self) -> None:
        bw, bh = self.size
        draw_spinner(bw, bh)

    def draw_border(self) -> None:
        bw, bh = self.size
        #double size since half the line will be off-screen
        log("draw_border: %s", self.border)
        glLineWidth(self.border.size*2)
        glBegin(GL_LINE_LOOP)
        glColor4f(self.border.red, self.border.green, self.border.blue, self.border.alpha)
        for px,py in ((0, 0), (bw, 0), (bw, bh), (0, bh)):
            glVertex2i(px, py)
        glEnd()

    def update_fps_buffer(self, width, height, pixels) -> None:
        #we always call 'record_fps_event' from a gl context,
        #so it is safe to upload the texture:
        self.upload_rgba_texture(self.textures[TEX_FPS], width, height, pixels)

    def draw_fps(self) -> None:
        x, y = 2, 5
        width, height = self.fps_buffer_size
        self.blend_texture(self.textures[TEX_FPS], x, y, width, height)
        self.cancel_fps_refresh()
        def refresh_screen(context):
            self.fps_refresh_timer = 0
            log("refresh_screen(%s)", context)
            if not self.paint_screen:
                return
            if context:
                self.update_fps()
                self.managed_present_fbo()
        self.fps_refresh_timer = GLib.timeout_add(1000, self.with_gl_context, refresh_screen)


    def validate_cursor(self) -> bool:
        cursor_data = self.cursor_data
        cw : int = cursor_data[3]
        ch : int = cursor_data[4]
        pixels = cursor_data[8]
        blen = cw*ch*4
        if len(pixels)!=blen:
            log.error("Error: invalid cursor pixel buffer for %ix%i", cw, ch)
            log.error(" expected %i bytes but got %i (%s)", blen, len(pixels), type(pixels))
            log.error(" %s", repr_ellipsized(hexstr(pixels)))
            return False
        return True

    def set_cursor_data(self, cursor_data) -> None:
        if (not cursor_data or len(cursor_data)==1) and self.default_cursor_data:
            cursor_data = list(self.default_cursor_data)
        if not cursor_data:
            return
        self.cursor_data = cursor_data
        if not cursor_data:
            return
        cw = cursor_data[3]
        ch = cursor_data[4]
        pixels = cursor_data[8]
        if not self.validate_cursor():
            return
        def gl_upload_cursor(context):
            if context:
                self.gl_init()
                self.upload_rgba_texture(self.textures[TEX_CURSOR], cw, ch, pixels)
        self.with_gl_context(gl_upload_cursor)

    def upload_rgba_texture(self, texture, width : int, height : int, pixels) -> None:
        upload, pixel_data = self.pixels_for_upload(pixels)
        rgb_format = "RGBA"
        glActiveTexture(GL_TEXTURE0)
        target = GL_TEXTURE_RECTANGLE_ARB
        glEnable(target)
        glBindTexture(target, texture)
        self.set_alignment(width, width*4, rgb_format)
        glTexParameteri(target, GL_TEXTURE_MAG_FILTER, GL_NEAREST)
        glTexParameteri(target, GL_TEXTURE_MIN_FILTER, GL_NEAREST)
        glTexParameteri(target, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_BORDER)
        glTexParameteri(target, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_BORDER)
        glTexImage2D(target, 0, GL_RGBA8, width, height, 0, GL_RGBA, GL_UNSIGNED_BYTE, pixel_data)
        log("upload_rgba_texture %ix%i uploaded %i bytes of %s pixel data using %s",
            width, height, len(pixels), rgb_format, upload)
        glBindTexture(target, 0)
        glDisable(target)

    def paint_box(self, encoding : str, x : int, y : int, w : int, h : int) -> None:
        #show region being painted if debug paint box is enabled only:
        if self.paint_box_line_width<=0:
            return
        glLineWidth(self.paint_box_line_width+0.5+int(encoding=="scroll")*2)
        glBegin(GL_LINE_LOOP)
        color = get_paint_box_color(encoding)
        log("Painting colored box around %s screen update using: %s", encoding, color)
        glColor4f(*color)
        for px,py in ((x, y), (x+w, y), (x+w, y+h), (x, y+h)):
            glVertex2i(px, py)
        glEnd()


    def pixels_for_upload(self, img_data) -> Tuple[str, Any]:
        #prepare the pixel buffer for upload:
        if isinstance(img_data, memoryview):
            if not zerocopy_upload:
                #not safe, make a copy :(
                return "copy:memoryview.tobytes", img_data.tobytes()
            return "zerocopy:memoryview", img_data
        if isinstance(img_data, bytes) and zerocopy_upload:
            #we can zerocopy if we wrap it:
            return "zerocopy:bytes-as-memoryview", memoryview(img_data)
        if isinstance(img_data, bytes):
            return "copy:bytes", img_data
        if hasattr(img_data, "raw"):
            return "zerocopy:mmap", img_data.raw
        # everything else: copy to bytes (aka str):
        return f"copy:bytes({type(img_data)})", strtobytes(img_data)

    def set_alignment(self, width : int, rowstride : int, pixel_format:str) -> None:
        bytes_per_pixel = len(pixel_format)       #ie: BGRX -> 4, Y -> 1, YY -> 2
        # Compute alignment and row length
        row_length = 0
        alignment = 1
        for a in (2, 4, 8):
            # Check if we are a-aligned - ! (var & 0x1) means 2-aligned or better, 0x3 - 4-aligned and so on
            if (rowstride & a-1) == 0:
                alignment = a
        # If number of extra bytes is greater than the alignment value,
        # then we also have to set row_length
        # Otherwise it remains at 0 (= width implicitly)
        if (rowstride - width * bytes_per_pixel) >= alignment:
            row_length = width + (rowstride - width * bytes_per_pixel) // bytes_per_pixel
        glPixelStorei(GL_UNPACK_ROW_LENGTH, row_length)
        glPixelStorei(GL_UNPACK_ALIGNMENT, alignment)
        #self.gl_marker("set_alignment%s GL_UNPACK_ROW_LENGTH=%i, GL_UNPACK_ALIGNMENT=%i",
        #               (width, rowstride, pixel_format), row_length, alignment)


    def paint_jpeg(self, img_data, x, y, width, height, options, callbacks) -> None:
        self.do_paint_jpeg("jpeg", img_data, x, y, width, height, options, callbacks)

    def paint_jpega(self, img_data, x, y, width, height, options, callbacks) -> None:
        self.do_paint_jpeg("jpega", img_data, x, y, width, height, options, callbacks)

    def do_paint_jpeg(self, encoding, img_data, x : int, y : int, width : int, height : int, options, callbacks) -> None:
        #log(f"do_paint_jpeg {width}x{height} NVJPEG={NVJPEG}/{self.nvjpeg_decoder}, NVDEC={NVDEC}/{self.nvdec_decoder}")
        if width>=16 and height>=16:
            if self.nvjpeg_decoder and NVJPEG:
                def paint_nvjpeg(gl_context):
                    self.paint_nvjpeg(gl_context, encoding, img_data, x, y, width, height, options, callbacks)
                self.idle_add(self.with_gl_context, paint_nvjpeg)
                return
            if self.nvdec_decoder and NVDEC and encoding in self.nvdec_decoder.get_encodings():
                def paint_nvdec(gl_context):
                    self.paint_nvdec(gl_context, encoding, img_data, x, y, width, height, options, callbacks)
                self.idle_add(self.with_gl_context, paint_nvdec)
                return
        if JPEG_YUV and width>=2 and height>=2 and encoding=="jpeg":
            img = self.jpeg_decoder.decompress_to_yuv(img_data)
            flush = options.intget("flush", 0)
            w = img.get_width()
            h = img.get_height()
            self.idle_add(self.gl_paint_planar, YUV_to_RGB_FULL_SHADER, flush, encoding, img,
                          x, y, w, h, width, height, options, callbacks)
            return
        if encoding=="jpeg":
            img = self.jpeg_decoder.decompress_to_rgb("BGRX", img_data)
        elif encoding=="jpega":
            alpha_offset = options.intget("alpha-offset", 0)
            img = self.jpeg_decoder.decompress_to_rgb("BGRA", img_data, alpha_offset)
        else:
            raise ValueError(f"invalid encoding {encoding}")
        w = img.get_width()
        h = img.get_height()
        rgb_format = img.get_pixel_format()
        self.idle_add(self.do_paint_rgb, rgb_format, img.get_pixels(), x, y, w, h, width, height,
                      img.get_rowstride(), options, callbacks)

    def cuda_buffer_to_pbo(self, cuda_buffer, rowstride:int, src_y:int, height:int, stream):
        #must be called with an active cuda context, and from the UI thread
        self.gl_init()
        pbo = glGenBuffers(1)
        size = rowstride*height
        glBindBuffer(GL_PIXEL_UNPACK_BUFFER, pbo)
        glBufferData(GL_PIXEL_UNPACK_BUFFER, size, None, GL_STREAM_DRAW)
        glBindBuffer(GL_PIXEL_UNPACK_BUFFER, 0)
        #pylint: disable=import-outside-toplevel
        from pycuda.driver import Memcpy2D   #pylint: disable=no-name-in-module
        from pycuda.gl import RegisteredBuffer, graphics_map_flags  # @UnresolvedImport
        cuda_pbo = RegisteredBuffer(int(pbo), graphics_map_flags.WRITE_DISCARD)
        log("RegisteredBuffer%s=%s", (pbo, graphics_map_flags.WRITE_DISCARD), cuda_pbo)
        mapping = cuda_pbo.map(stream)
        ptr, msize = mapping.device_ptr_and_size()
        if msize<size:
            raise ValueError(f"registered buffer size {msize} too small for pbo size {size}")
        log("copying %i bytes from %s to mapping=%s at %#x", size, cuda_buffer, mapping, ptr)
        copy = Memcpy2D()
        copy.src_pitch = rowstride
        copy.src_y = src_y
        copy.set_src_device(cuda_buffer)
        copy.dst_pitch = rowstride
        copy.set_dst_device(ptr)
        copy.width_in_bytes = rowstride
        copy.height = height
        copy(stream)
        mapping.unmap(stream)
        stream.synchronize()
        cuda_pbo.unregister()
        return pbo

    def paint_nvdec(self, gl_context, encoding, img_data, x : int, y : int, width : int, height : int,
                    options, callbacks) -> None:
        with self.assign_cuda_context(True):
            #we can import pycuda safely here,
            #because `self.assign_cuda_context` will have imported it with the lock:
            from pycuda.driver import Stream, LogicError  # @UnresolvedImport pylint: disable=import-outside-toplevel
            stream = Stream()
            options["stream"] = stream
            img = self.nvdec_decoder.decompress_with_device(encoding, img_data, width, height, options)
            log("paint_nvdec: gl_context=%s, img=%s, downloading buffer to pbo", gl_context, img)
            pixel_format = img.get_pixel_format()
            if pixel_format not in ("NV12", ):
                raise ValueError(f"unexpected pixel format {pixel_format}")
            #'pixels' is a cuda buffer with 2 planes: Y then UV
            cuda_buffer = img.get_pixels()
            strides = img.get_rowstride()
            height = img.get_height()
            try:
                y_pbo = self.cuda_buffer_to_pbo(cuda_buffer, strides[0], 0, height, stream)
                uv_pbo = self.cuda_buffer_to_pbo(cuda_buffer, strides[1], roundup(height, 2), height//2, stream)
            except LogicError as e:
                #disable nvdec from now on:
                self.nvdec_decoder = None
                log("paint_nvdec%s", (gl_context, encoding, img_data, x, y, width, height, options, callbacks))
                raise RuntimeError(f"failed to download nvdec cuda buffer to pbo: {e}")
            finally:
                cuda_buffer.free()
            img.set_pixels((y_pbo, uv_pbo))

        flush = options.intget("flush", 0)
        w = img.get_width()
        h = img.get_height()
        options["pbo"] = True
        self.do_gl_paint_planar(gl_context, NV12_to_RGB_SHADER, flush, encoding, img,
                           x, y, w, h, width, height,
                           options, callbacks)

    def paint_nvjpeg(self, gl_context, encoding, img_data, x : int, y : int, width : int, height : int,
                     options, callbacks) -> None:
        with self.assign_cuda_context(True):
            #we can import pycuda safely here,
            #because `self.assign_cuda_context` will have imported it with the lock:
            from pycuda.driver import Stream  # @UnresolvedImport pylint: disable=import-outside-toplevel
            stream = Stream()
            options["stream"] = stream
            img = self.nvjpeg_decoder.decompress_with_device("RGB", img_data, options)
            log("paint_nvjpeg: gl_context=%s, img=%s, downloading buffer to pbo", gl_context, img)
            rgb_format = img.get_pixel_format()
            if rgb_format not in ("RGB", "BGR", "RGBA", "BGRA"):
                raise ValueError(f"unexpected rgb format {rgb_format}")
            #'pixels' is a cuda buffer:
            cuda_buffer = img.get_pixels()
            pbo = self.cuda_buffer_to_pbo(cuda_buffer, img.get_rowstride(), 0, img.get_height(), stream)
            cuda_buffer.free()

        pformat = PIXEL_FORMAT_TO_CONSTANT[rgb_format]
        target = GL_TEXTURE_RECTANGLE_ARB
        glEnable(target)
        glBindTexture(target, self.textures[TEX_RGB])
        glBindBuffer(GL_PIXEL_UNPACK_BUFFER, pbo)
        glPixelStorei(GL_UNPACK_ROW_LENGTH, 0)
        glPixelStorei(GL_UNPACK_ALIGNMENT, 1)
        glTexImage2D(target, 0, self.internal_format, width, height, 0, pformat, GL_UNSIGNED_BYTE, None)
        glBindBuffer(GL_PIXEL_UNPACK_BUFFER, 0)

        self.set_alignment(width, width*len(rgb_format), rgb_format)
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

        self.paint_box(encoding, x, y, width, height)
        # Present update to screen
        if not self.draw_needs_refresh:
            self.present_fbo(x, y, width, height, options.intget("flush", 0))
        # present_fbo has reset state already
        fire_paint_callbacks(callbacks)
        glDeleteBuffers(1, [pbo])


    def paint_webp(self, img_data, x : int, y : int, width : int, height : int, options, callbacks) -> None:
        subsampling = options.strget("subsampling")
        has_alpha = options.boolget("has_alpha")
        if subsampling=="YUV420P" and WEBP_YUV and self.webp_decoder and not WEBP_PILLOW and not has_alpha and width>=2 and height>=2:
            img = self.webp_decoder.decompress_yuv(img_data)
            flush = options.intget("flush", 0)
            w = img.get_width()
            h = img.get_height()
            self.idle_add(self.gl_paint_planar, YUV_to_RGB_SHADER, flush, "webp", img,
                          x, y, w, h, width, height, options, callbacks)
            return
        super().paint_webp(img_data, x, y, width, height, options, callbacks)

    def paint_avif(self, img_data, x:int, y:int, width:int, height:int, options, callbacks) -> None:
        alpha = options.boolget("alpha")
        img = self.avif_decoder.decompress(img_data, options, yuv=not alpha)
        pixel_format = img.get_pixel_format()
        flush = options.intget("flush", 0)
        w = img.get_width()
        h = img.get_height()
        if pixel_format.startswith("YUV"):
            self.idle_add(self.gl_paint_planar, YUV_to_RGB_FULL_SHADER, flush, "avif", img,
                          x, y, w, h, width, height, options, callbacks)
        else:
            self.idle_add(self.do_paint_rgb, pixel_format, img.get_pixels(), x, y, w, h, width, height,
                          img.get_rowstride(), options, callbacks)

    def do_paint_rgb(self, rgb_format:str, img_data,
                     x : int, y : int, width : int, height : int, render_width : int, render_height : int,
                     rowstride, options, callbacks) -> None:
        self.with_gl_context(self.gl_paint_rgb,
                             rgb_format, img_data,
                             x, y, width, height,
                             render_width, render_height, rowstride, options, callbacks)

    def gl_paint_rgb(self, context, rgb_format:str, img_data,
                     x : int, y : int, width : int, height : int, render_width : int, render_height : int,
                     rowstride, options, callbacks):
        log("%s.gl_paint_rgb(%s, %s bytes, x=%d, y=%d, width=%d, height=%d, rowstride=%d, options=%s)",
            self, rgb_format, len(img_data), x, y, width, height, rowstride, options)
        x, y = self.gravity_adjust(x, y, options)
        if not context:
            log("%s.gl_paint_rgb(..) no context!", self)
            fire_paint_callbacks(callbacks, False, "no opengl context")
            return
        if not options.boolget("paint", True):
            fire_paint_callbacks(callbacks)
            return
        rgb_format = bytestostr(rgb_format)
        try:
            upload, img_data = self.pixels_for_upload(img_data)

            self.gl_init()
            scaling = width!=render_width or height!=render_height

            #convert it to a GL constant:
            pformat = PIXEL_FORMAT_TO_CONSTANT.get(rgb_format)
            if pformat is None:
                raise ValueError(f"could not find pixel format for {rgb_format!r}")
            ptype = PIXEL_UPLOAD_FORMAT.get(rgb_format)
            if pformat is None:
                raise ValueError(f"could not find pixel type for {rgb_format!r}")

            self.gl_marker("%s update at (%d,%d) size %dx%d (%s bytes) to %dx%d, using GL %s format=%s / %s to internal format=%s",
                           rgb_format, x, y, width, height, len(img_data), render_width, render_height,
                           upload, CONSTANT_TO_PIXEL_FORMAT.get(pformat), DATATYPE_TO_STR.get(ptype), INTERNAL_FORMAT_TO_STR.get(self.internal_format))

            # Upload data as temporary RGB texture
            target = GL_TEXTURE_RECTANGLE_ARB
            glEnable(target)
            glBindTexture(target, self.textures[TEX_RGB])
            self.set_alignment(width, rowstride, rgb_format)
            mag_filter = GL_NEAREST
            if scaling:
                mag_filter = GL_LINEAR
            glTexParameteri(target, GL_TEXTURE_MAG_FILTER, mag_filter)
            glTexParameteri(target, GL_TEXTURE_MIN_FILTER, GL_NEAREST)
            glTexParameteri(target, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_BORDER)
            glTexParameteri(target, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_BORDER)
            glTexImage2D(target, 0, self.internal_format, width, height, 0, pformat, ptype, img_data)

            # Draw textured RGB quad at the right coordinates
            glBegin(GL_QUADS)
            glTexCoord2i(0, 0)
            glVertex2i(x, y)
            glTexCoord2i(0, height)
            glVertex2i(x, y+render_height)
            glTexCoord2i(width, height)
            glVertex2i(x+render_width, y+render_height)
            glTexCoord2i(width, 0)
            glVertex2i(x+render_width, y)
            glEnd()

            glBindTexture(target, 0)
            glDisable(target)
            self.paint_box(options.strget("encoding"), x, y, render_width, render_height)
            # Present update to screen
            if not self.draw_needs_refresh:
                self.present_fbo(x, y, render_width, render_height, options.intget("flush", 0))
            # present_fbo has reset state already
            fire_paint_callbacks(callbacks)
            return
        except GLError as e:
            message = f"OpenGL {rgb_format} paint failed: {e}"
            log("Error in %s paint of %i bytes, options=%s", rgb_format, len(img_data), options, exc_info=True)
        except Exception as e:
            message = f"OpenGL {rgb_format} paint error: {e}"
            log("Error in %s paint of %i bytes, options=%s", rgb_format, len(img_data), options, exc_info=True)
        fire_paint_callbacks(callbacks, False, message)


    def do_video_paint(self, img,
                       x : int, y : int, enc_width : int, enc_height : int, width : int, height : int,
                       options, callbacks):
        log("do_video_paint%s", (x, y, enc_width, enc_height, width, height, options, callbacks))
        if not zerocopy_upload or FORCE_CLONE:
            #copy so the data will be usable (usually a str)
            img.clone_pixel_data()
        pixel_format = img.get_pixel_format()
        if FORCE_VIDEO_PIXEL_FORMAT:
            cd = self.make_csc(enc_width, enc_height, pixel_format,
                                width, height, (FORCE_VIDEO_PIXEL_FORMAT, ))
            img = cd.convert_image(img)
            pixel_format = img.get_pixel_format()
            log.warn(f"converting to {pixel_format} using {cd}")
            log.warn(f" img={img}")
            log.warn(f" rowstride={img.get_rowstride()}, {pixel_format}")
            cd.clean()
        if pixel_format in ("GBRP10", "YUV444P10"):
            #call superclass to handle csc
            #which will end up calling paint rgb with r210 data
            super().do_video_paint(img, x, y, enc_width, enc_height, width, height, options, callbacks)
            return
        if pixel_format.startswith("GBRP"):
            shader = RGBP_to_RGB_SHADER
        elif pixel_format=="NV12":
            shader = NV12_to_RGB_SHADER
        else:
            shader = YUV_to_RGB_SHADER
        self.idle_add(self.gl_paint_planar, shader, options.intget("flush", 0), options.strget("encoding"), img,
                      x, y, enc_width, enc_height, width, height, options, callbacks)

    def gl_paint_planar(self, shader, flush:int, encoding:str, img,
                        x : int, y : int, enc_width : int, enc_height : int, width : int, height : int,
                        options, callbacks):
        #this function runs in the UI thread, no video_decoder lock held
        log("gl_paint_planar%s", (flush, encoding, img, x, y, enc_width, enc_height, width, height, options, callbacks))
        self.with_gl_context(self.do_gl_paint_planar, shader, flush, encoding, img,
                             x, y, enc_width, enc_height,
                             width, height, options, callbacks)

    def do_gl_paint_planar(self, context, shader, flush:int, encoding:str, img,
                           x : int, y : int, enc_width : int, enc_height : int, width : int, height : int,
                           options, callbacks):
        x, y = self.gravity_adjust(x, y, options)
        try:
            pixel_format = img.get_pixel_format()
            if pixel_format not in ("YUV420P", "YUV422P", "YUV444P", "GBRP", "NV12", "GBRP16", "YUV444P16"):
                raise ValueError(f"the GL backing does not handle pixel format {pixel_format!r} yet!")
            if not context:
                log("%s._do_paint_rgb(..) no OpenGL context!", self)
                fire_paint_callbacks(callbacks, False, "failed to get a gl context")
                return
            self.gl_init()
            scaling = enc_width!=width or enc_height!=height
            self.update_planar_textures(enc_width, enc_height, img, pixel_format, scaling=scaling, pbo=options.get("pbo"))

            # Update FBO texture
            x_scale, y_scale = 1.0, 1.0
            if scaling:
                x_scale = width/enc_width
                y_scale = height/enc_height

            self.render_planar_update(x, y, enc_width, enc_height, x_scale, y_scale, shader)
            self.paint_box(encoding, x, y, width, height)
            fire_paint_callbacks(callbacks, True)
            # Present it on screen
            if not self.draw_needs_refresh:
                self.present_fbo(x, y, width, height, flush)
            img.free()
            return
        except GLError as e:
            message = f"OpenGL {encoding} paint failed: {e!r}"
            log.error("Error painting planar update", exc_info=True)
        except Exception as e:
            message = f"OpenGL {encoding} paint failed: {e}"
            log.error("Error painting planar update", exc_info=True)
        log.error(" flush=%i, image=%s, coords=%s, size=%ix%i",
                  flush, img, (x, y, enc_width, enc_height), width, height)
        fire_paint_callbacks(callbacks, False, message)

    def update_planar_textures(self, width : int, height : int, img, pixel_format, scaling:bool=False, pbo:bool=False):
        assert self.textures is not None, "no OpenGL textures!"
        upload_formats = PIXEL_UPLOAD_FORMAT[pixel_format]
        internal_formats = PIXEL_INTERNAL_FORMAT.get(pixel_format, (GL_R8, GL_R8, GL_R8))
        data_formats = PIXEL_DATA_FORMAT.get(pixel_format, (GL_RED, GL_RED, GL_RED))
        divs = get_subsampling_divs(pixel_format)
        BPP = 2 if (pixel_format.endswith("P16") or pixel_format.endswith("P10")) else 1
        #textures: usually 3, but only 2 for "NV12"
        textures = (
            (GL_TEXTURE0, TEX_Y),
            (GL_TEXTURE1, TEX_U),
            (GL_TEXTURE2, TEX_V),
            )[:len(divs)]
        log("%s.update_planar_textures%s textures=%s", self, (width, height, img, pixel_format, scaling, pbo), textures)
        if self.pixel_format!=pixel_format or self.texture_size!=(width, height):
            self.gl_marker("Creating new planar textures, pixel format %s (was %s), texture size %s (was %s)",
                           pixel_format, self.pixel_format, (width, height), self.texture_size)
            self.pixel_format = pixel_format
            self.texture_size = (width, height)
            # Create textures of the same size as the window's
            for texture, index in textures:
                (div_w, div_h) = divs[index]
                glActiveTexture(texture)
                target = GL_TEXTURE_RECTANGLE_ARB
                glBindTexture(target, self.textures[index])
                mag_filter = GL_NEAREST
                if scaling or (div_w > 1 or div_h > 1):
                    mag_filter = GL_LINEAR
                glTexParameteri(target, GL_TEXTURE_MAG_FILTER, mag_filter)
                glTexParameteri(target, GL_TEXTURE_MIN_FILTER, GL_NEAREST)

                iformat = internal_formats[index]
                dformat = data_formats[index]
                uformat = upload_formats[index]     #upload format: ie: UNSIGNED_BYTE
                glTexImage2D(target, 0, iformat, width//div_w, height//div_h, 0, dformat, uformat, None)
                #glBindTexture(target, 0)        #redundant: we rebind below:

        self.gl_marker("updating planar textures: %sx%s %s", width, height, pixel_format)
        rowstrides = img.get_rowstride()
        img_data = img.get_pixels()
        if len(rowstrides)!=len(divs) or len(img_data)!=len(divs):
            raise RuntimeError(f"invalid number of planes for {pixel_format}")
        for texture, index in textures:
            #"YUV420P" -> ("Y", "U", "V")
            #"GBRP16" -> ("GG", "BB", "RR")
            #"NV12" -> ("Y", "UV")
            tex_name = get_plane_name(pixel_format, index) * BPP
            dformat = data_formats[index]       #data format: ie: GL_RED
            uformat = upload_formats[index]     #upload format: ie: UNSIGNED_BYTE
            rowstride = rowstrides[index]
            div_w, div_h = divs[index]
            w = width//div_w
            if dformat==GL_LUMINANCE_ALPHA:
                #uploading 2 components
                w //= 2
            elif dformat not in (GL_RED, GL_LUMINANCE):
                raise RuntimeError(f"unexpected data format {dformat} for {pixel_format}")
            h = height//div_h
            if w==0 or h==0:
                log.error(f"Error: zero dimension {w}x{h} for {pixel_format} planar texture {tex_name}")
                log.error(f" screen update {width}x{height} dropped, div={div_w}x{div_h}")
                continue
            glActiveTexture(texture)

            target = GL_TEXTURE_RECTANGLE_ARB
            glBindTexture(target, self.textures[index])
            self.set_alignment(w, rowstride, tex_name)
            plane = img_data[index]
            if pbo:
                upload = "pbo"
                glBindBuffer(GL_PIXEL_UNPACK_BUFFER, plane)
                pixel_data = None
                size = rowstride*h
            else:
                upload, pixel_data = self.pixels_for_upload(plane)
                size = len(pixel_data)
            glTexParameteri(target, GL_TEXTURE_BASE_LEVEL, 0)
            try:
                glTexParameteri(target, GL_TEXTURE_MAX_LEVEL, 0)
            except Exception:
                pass
            log(f"texture {index}: {tex_name:2} div={div_w},{div_h}, rowstride={rowstride}, {w}x{h}, "+
                f"data={size} bytes, upload={upload}, format={dformat}, type={uformat}")
            glTexSubImage2D(target, 0, 0, 0, w, h, dformat, uformat, pixel_data)
            glBindTexture(target, 0)
            glBindBuffer(GL_PIXEL_UNPACK_BUFFER, 0)
        #glActiveTexture(GL_TEXTURE0)    #redundant, we always call render_planar_update afterwards

    def render_planar_update(self, rx : int, ry : int, rw : int, rh : int, x_scale=1.0, y_scale=1.0, shader:int=YUV_to_RGB_SHADER):
        log("%s.render_planar_update%s pixel_format=%s",
            self, (rx, ry, rw, rh, x_scale, y_scale, shader), self.pixel_format)
        if self.pixel_format not in ("YUV420P", "YUV422P", "YUV444P", "GBRP", "NV12", "GBRP16", "YUV444P16"):
            #not ready to render yet
            return
        divs = get_subsampling_divs(self.pixel_format)
        textures = (
            (GL_TEXTURE0, TEX_Y),
            (GL_TEXTURE1, TEX_U),
            (GL_TEXTURE2, TEX_V),
            )[:len(divs)]
        self.gl_marker("painting planar update, format %s", self.pixel_format)
        glBindProgramARB(GL_FRAGMENT_PROGRAM_ARB, self.shaders[shader])
        glEnable(GL_FRAGMENT_PROGRAM_ARB)
        for texture, index in textures:
            glActiveTexture(texture)
            glBindTexture(GL_TEXTURE_RECTANGLE_ARB, self.textures[index])

        tw, th = self.texture_size
        log("%s.render_planar_update(..) texture_size=%s, size=%s", self, self.texture_size, self.size)
        glBegin(GL_QUADS)
        for x,y in ((0, 0), (0, rh), (rw, rh), (rw, 0)):
            ax = min(tw, x)
            ay = min(th, y)
            for texture, index in textures:
                div_w, div_h = divs[index]
                #same as GL_LUMINANCE_ALPHA in update_planar_textures,
                #NV12's second plane combines `U` and `V`:
                if index==1 and self.pixel_format=="NV12":
                    div_w *= 2
                glMultiTexCoord2i(texture, ax//div_w, ay//div_h)
            glVertex2i(int(rx+ax*x_scale), int(ry+ay*y_scale))
        glEnd()
        for texture in (GL_TEXTURE0, GL_TEXTURE1, GL_TEXTURE2):
            glActiveTexture(texture)
            glBindTexture(GL_TEXTURE_RECTANGLE_ARB, 0)
        glDisable(GL_FRAGMENT_PROGRAM_ARB)
        glActiveTexture(GL_TEXTURE0)


    def gl_show(self, rect_count) -> None:
        start = monotonic()
        self.do_gl_show(rect_count)
        end = monotonic()
        flush_elapsed = end-self.last_flush
        self.last_flush = end
        fpslog("gl_show after %3ims took %2ims, %2i updates", flush_elapsed*1000, (end-start)*1000, rect_count)


    def gl_expose_rect(self, rect=None) -> None:
        if not self.paint_screen:
            return
        if not rect:
            w, h = self.size
            rect = (0, 0, w, h)
        def expose(context):
            if context:
                self.gl_init()
                self.present_fbo(*rect)
        self.with_gl_context(expose)
