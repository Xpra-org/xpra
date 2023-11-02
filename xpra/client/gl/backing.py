# This file is part of Xpra.
# Copyright (C) 2013 Serviware (Arthur Huillet, <ahuillet@serviware.com>)
# Copyright (C) 2012-2023 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import struct
from time import monotonic
from typing import Any
from ctypes import c_float, c_void_p
from collections.abc import Callable, Iterable
from contextlib import AbstractContextManager, nullcontext
from gi.repository import GLib  # @UnresolvedImport

from OpenGL.error import GLError
from OpenGL.constant import IntConstant
from OpenGL.GL import (
    GLuint,
    GL_PIXEL_UNPACK_BUFFER, GL_STREAM_DRAW,
    GL_UNPACK_ROW_LENGTH, GL_UNPACK_ALIGNMENT,
    GL_TEXTURE_MAG_FILTER, GL_TEXTURE_MIN_FILTER, GL_NEAREST,
    GL_UNSIGNED_BYTE, GL_UNSIGNED_SHORT,
    GL_LINEAR, GL_RED, GL_R8, GL_R16, GL_LUMINANCE, GL_LUMINANCE_ALPHA,
    GL_TEXTURE0, GL_TEXTURE1, GL_TEXTURE2, GL_QUADS, GL_LINES, GL_COLOR_BUFFER_BIT,
    GL_TEXTURE_WRAP_S, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_BORDER,
    GL_DEPTH_TEST, GL_SCISSOR_TEST, GL_DITHER,
    GL_RGB, GL_RGBA, GL_BGR, GL_BGRA, GL_RGBA8, GL_RGB8, GL_RGB10_A2, GL_RGB565, GL_RGB5_A1, GL_RGBA4, GL_RGBA16,
    GL_UNSIGNED_INT_2_10_10_10_REV, GL_UNSIGNED_INT_10_10_10_2, GL_UNSIGNED_SHORT_5_6_5,
    GL_BLEND, GL_ONE, GL_ONE_MINUS_SRC_ALPHA,
    GL_TEXTURE_MAX_LEVEL, GL_TEXTURE_BASE_LEVEL,
    glBlendFunc,
    glActiveTexture, glTexSubImage2D,
    glViewport,
    glGenTextures, glDisable,
    glBindTexture, glPixelStorei, glEnable, glBegin, glFlush,
    glBindBuffer, glGenBuffers, glBufferData, glDeleteBuffers,
    glTexParameteri,
    glTexImage2D,
    glTexCoord2i, glVertex2i, glEnd,
    glClear, glClearColor, glLineWidth, glColor4f,
    glDrawBuffer, glReadBuffer,
    GL_FLOAT, GL_ARRAY_BUFFER,
    GL_STATIC_DRAW, GL_FALSE,
    glDrawArrays, GL_TRIANGLE_STRIP,
    glEnableVertexAttribArray, glVertexAttribPointer, glDisableVertexAttribArray,
    glGenVertexArrays, glBindVertexArray, glDeleteVertexArrays,
    glUseProgram, GL_TEXTURE_RECTANGLE, glGetUniformLocation, glUniform1i, glUniform2f,
)
from OpenGL.GL.ARB.framebuffer_object import (
    GL_FRAMEBUFFER, GL_DRAW_FRAMEBUFFER, GL_READ_FRAMEBUFFER,
    GL_COLOR_ATTACHMENT0, GL_COLOR_ATTACHMENT1,
    glGenFramebuffers, glBindFramebuffer, glFramebufferTexture2D, glBlitFramebuffer,
    )

from xpra.os_util import (
    bytestostr, hexstr,
    POSIX, OSX, first_time,
)
from xpra.util.str_fn import repr_ellipsized, nonl
from xpra.util.env import envint, envbool
from xpra.util.types import typedict
from xpra.common import roundup
from xpra.codecs.constants import get_subsampling_divs, get_plane_name
from xpra.client.gui.window_border import WindowBorder
from xpra.client.gui.paint_colors import get_paint_box_color
from xpra.client.gui.window_backing_base import (
    fire_paint_callbacks, WindowBackingBase,
    WEBP_PILLOW,
    )
from xpra.client.gl.check import GL_ALPHA_SUPPORTED, get_max_texture_size
from xpra.client.gl.debug import context_init_debug, gl_marker, gl_frame_terminator
from xpra.client.gl.util import (
    save_fbo, SAVE_BUFFERS,
    zerocopy_upload, pixels_for_upload, set_alignment, upload_rgba_texture,
)
from xpra.client.gl.spinner import draw_spinner
from xpra.log import Logger

log = Logger("opengl", "paint")
fpslog = Logger("opengl", "fps")


OPENGL_DEBUG = envbool("XPRA_OPENGL_DEBUG", False)
PAINT_FLUSH = envbool("XPRA_PAINT_FLUSH", True)
JPEG_YUV = envbool("XPRA_JPEG_YUV", True)
WEBP_YUV = envbool("XPRA_WEBP_YUV", True)
FORCE_CLONE = envbool("XPRA_OPENGL_FORCE_CLONE", False)
FORCE_VIDEO_PIXEL_FORMAT = os.environ.get("XPRA_FORCE_VIDEO_PIXEL_FORMAT", "")
DRAW_REFRESH = envbool("XPRA_OPENGL_DRAW_REFRESH", True)
FBO_RESIZE = envbool("XPRA_OPENGL_FBO_RESIZE", True)
FBO_RESIZE_DELAY = envint("XPRA_OPENGL_FBO_RESIZE_DELAY", -1)
CONTEXT_REINIT = envbool("XPRA_OPENGL_CONTEXT_REINIT", False)
NVJPEG = envbool("XPRA_OPENGL_NVJPEG", True)
NVDEC = envbool("XPRA_OPENGL_NVDEC", False)

CURSOR_IDLE_TIMEOUT: int = envint("XPRA_CURSOR_IDLE_TIMEOUT", 6)


PIXEL_FORMAT_TO_CONSTANT : dict[str,IntConstant] = {
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
PIXEL_INTERNAL_FORMAT : dict[str,tuple[IntConstant,...]] = {
    # defaults to: GL_R8, GL_R8, GL_R8
    # (meaning: 3 planes, 8 bits each)
    # override for formats that use 16 bit per channel:
    "NV12" : (GL_LUMINANCE, GL_LUMINANCE_ALPHA),
    "GBRP" : (GL_LUMINANCE, GL_LUMINANCE, GL_LUMINANCE),    # invalid according to the spec! (only value that works)
    "GBRP16" : (GL_R16, GL_R16, GL_R16),
    "YUV444P10" : (GL_R16, GL_R16, GL_R16),
    "YUV444P16" : (GL_R16, GL_R16, GL_R16),
}
PIXEL_DATA_FORMAT : dict[str,tuple[IntConstant,...]] = {
    # defaults to: (GL_RED, GL_RED, GL_RED))
    # (meaning: uploading one channel at a time)
    "NV12"  : (GL_LUMINANCE, GL_LUMINANCE_ALPHA),  # Y is one channel, UV contains two channels
}
PIXEL_UPLOAD_FORMAT : dict[str,Any] = {
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
    # planar formats:
    "NV12"  : (GL_UNSIGNED_BYTE, GL_UNSIGNED_BYTE),
    "YUV420P" : (GL_UNSIGNED_BYTE, GL_UNSIGNED_BYTE, GL_UNSIGNED_BYTE),
    "YUV422P" : (GL_UNSIGNED_BYTE, GL_UNSIGNED_BYTE, GL_UNSIGNED_BYTE),
    "YUV444P" : (GL_UNSIGNED_BYTE, GL_UNSIGNED_BYTE, GL_UNSIGNED_BYTE),
    "GBRP"  : (GL_UNSIGNED_BYTE, GL_UNSIGNED_BYTE, GL_UNSIGNED_BYTE),
    "GBRP16" : (GL_UNSIGNED_SHORT, GL_UNSIGNED_SHORT, GL_UNSIGNED_SHORT),
    "YUV444P10" : (GL_UNSIGNED_SHORT, GL_UNSIGNED_SHORT, GL_UNSIGNED_SHORT),
    "YUV444P16" : (GL_UNSIGNED_SHORT, GL_UNSIGNED_SHORT, GL_UNSIGNED_SHORT),
}
CONSTANT_TO_PIXEL_FORMAT : dict[IntConstant,str] = {
    GL_BGR   : "BGR",
    GL_RGB   : "RGB",
    GL_BGRA  : "BGRA",
    GL_RGBA  : "RGBA",
    }
INTERNAL_FORMAT_TO_STR : dict[IntConstant,str] = {
    GL_RGB10_A2     : "RGB10_A2",
    GL_RGBA8        : "RGBA8",
    GL_RGB8         : "RGB8",
    GL_RGB565       : "RGB565",
    GL_RGB5_A1      : "RGB5_A1",
    GL_RGBA4        : "RGBA4",
    GL_RGBA16       : "GL_RGBA16",
}
DATATYPE_TO_STR : dict[IntConstant,str] = {
    GL_UNSIGNED_INT_2_10_10_10_REV  : "UNSIGNED_INT_2_10_10_10_REV",
    GL_UNSIGNED_INT_10_10_10_2      : "UNSIGNED_INT_10_10_10_2",
    GL_UNSIGNED_BYTE                : "UNSIGNED_BYTE",
    GL_UNSIGNED_SHORT               : "UNSIGNED_SHORT",
    GL_UNSIGNED_SHORT_5_6_5         : "UNSIGNED_SHORT_5_6_5",
}

paint_context_manager: AbstractContextManager = nullcontext()
if POSIX and not OSX:
    # pylint: disable=ungrouped-imports
    from xpra.gtk.error import xsync
    paint_context_manager = xsync


# Texture number assignment
# The first four are used to update the FBO,
# the FBO is what is painted on screen.
TEX_Y = 0
TEX_U = 1
TEX_V = 2
TEX_RGB = 3
TEX_FBO = 4         # FBO texture (guaranteed up-to-date window contents)
TEX_TMP_FBO = 5
TEX_CURSOR = 6
TEX_FPS = 7
N_TEXTURES = 8


class GLWindowBackingBase(WindowBackingBase):
    """
    The logic is as follows:

    We create an OpenGL framebuffer object, which will be always up-to-date with the latest windows contents.
    This framebuffer object is updated with YUV painting and RGB painting. It is presented on screen by drawing a
    textured quad when requested, that is: after each YUV or RGB painting operation, and upon receiving an expose event.
    The use of a intermediate framebuffer object is the only way to guarantee that the client keeps
    an always fully up-to-date window image, which is critical because of backbuffer content losses upon buffer swaps
    or offscreen window movement.
    """

    RGB_MODES : list[str] = ["YUV420P", "YUV422P", "YUV444P", "GBRP", "BGRA", "BGRX", "RGBA", "RGBX", "RGB", "BGR", "NV12"]
    HAS_ALPHA : bool = GL_ALPHA_SUPPORTED

    def __init__(self, wid: int, window_alpha: bool, pixel_depth: int = 0):
        self.wid: int = wid
        self.texture_pixel_format : IntConstant | None = None
        # this is the pixel format we are currently updating the fbo with
        # can be: "YUV420P", "YUV422P", "YUV444P", "GBRP" or None when not initialized yet.
        self.pixel_format : str = ""
        self.internal_format = GL_RGBA8
        self.textures = None # OpenGL texture IDs
        self.shaders : dict[str, GLuint] = {}
        self.programs : dict[str, GLuint] = {}
        self.texture_size : tuple[int, int] = (0, 0)
        self.gl_setup = False
        self.debug_setup = False
        self.border: WindowBorder = WindowBorder(shown=False)
        self.paint_screen = False
        self.paint_spinner = False
        self.offscreen_fbo = None
        self.tmp_fbo = None
        self.vao = None
        self.pending_fbo_paint : list[tuple[int,int,int,int]] = []
        self.last_flush = monotonic()
        self.last_present_fbo_error = ""
        self.bit_depth = pixel_depth
        super().__init__(wid, window_alpha and self.HAS_ALPHA)
        self.opengl_init()

    def opengl_init(self):
        self.init_gl_config()
        self.init_backing()
        self.bit_depth: int = self.get_bit_depth(self.bit_depth)
        self.init_formats()
        self.draw_needs_refresh : bool = DRAW_REFRESH
        # the correct check would be this:
        # `self.repaint_all = self.is_double_buffered() or bw!=ww or bh!=wh`
        # but we're meant to be using double-buffered everywhere,
        # so don't bother and just repaint everything:
        self.repaint_all : bool = True
        assert self._backing is not None
        self._backing.show()

    def get_info(self) -> dict[str,Any]:
        info = super().get_info()
        tpf = self.texture_pixel_format
        tif = self.internal_format
        info |= {
            "type"                  : "OpenGL",
            "bit-depth"             : self.bit_depth,
            "pixel-format"          : self.pixel_format,
            "texture-pixel-format"  : CONSTANT_TO_PIXEL_FORMAT.get(tpf) or str(tpf),
            "internal-format"       : INTERNAL_FORMAT_TO_STR.get(tif) or str(tif),
        }
        return info

    def with_gl_context(self, cb:Callable, *args):
        raise NotImplementedError()

    def init_gl_config(self) -> None:
        raise NotImplementedError()

    def init_backing(self) -> None:
        raise NotImplementedError()

    def gl_context(self):
        raise NotImplementedError()

    def do_gl_show(self, rect_count: int) -> None:
        raise NotImplementedError()

    def is_double_buffered(self) -> bool:
        raise NotImplementedError()

    def get_bit_depth(self, pixel_depth:int=0) -> int:
        return pixel_depth or 24

    def init_formats(self) -> None:
        self.RGB_MODES = list(GLWindowBackingBase.RGB_MODES)
        if self.bit_depth > 32:
            self.internal_format: int = GL_RGBA16
            self.RGB_MODES.append("r210")
            # self.RGB_MODES.append("GBRP16")
        elif self.bit_depth == 30:
            self.internal_format = GL_RGB10_A2
            self.RGB_MODES.append("r210")
            # self.RGB_MODES.append("GBRP16")
        elif 0 < self.bit_depth <= 16:
            if self._alpha_enabled:
                if envbool("XPRA_GL_RGBA4", True):
                    self.internal_format = GL_RGBA4
                else:
                    self.internal_format = GL_RGB5_A1
                    # too much of a waste to enable?
                    self.RGB_MODES.append("r210")
            else:
                self.internal_format = GL_RGB565
                self.RGB_MODES.append("BGR565")
                self.RGB_MODES.append("RGB565")
        else:
            if self.bit_depth not in (0, 24, 32) and first_time(f"bit-depth-{self.bit_depth}"):
                log.warn(f"Warning: invalid bit depth {self.bit_depth}, using 24")
            # assume 24:
            if self._alpha_enabled:
                self.internal_format = GL_RGBA8
            else:
                self.internal_format = GL_RGB8
        # (pixels are always stored in 32bpp - but this makes it clearer when we do/don't support alpha)
        if self._alpha_enabled:
            self.texture_pixel_format = GL_RGBA
        else:
            self.texture_pixel_format = GL_RGB
        log("init_formats() texture pixel format=%s, internal format=%s, rgb modes=%s",
            CONSTANT_TO_PIXEL_FORMAT.get(self.texture_pixel_format),
            INTERNAL_FORMAT_TO_STR.get(self.internal_format),
            self.RGB_MODES)

    def get_encoding_properties(self) -> dict[str,Any]:
        props = super().get_encoding_properties()
        props["encoding.bit-depth"] = self.bit_depth
        return props

    def __repr__(self):
        return f"GLWindowBacking({self.wid}, {self.size}, {self.pixel_format})"

    def init(self, ww: int, wh: int, bw: int, bh: int) -> None:
        # re-init gl projection with new dimensions
        # (see gl_init)
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

    def resize_fbo(self, context, oldw: int, oldh: int, bw: int, bh: int) -> None:
        log("resize_fbo%s offscreen_fbo=%s",
            (context, oldw, oldh, bw, bh), self.offscreen_fbo)
        if not context or self.offscreen_fbo is None:
            return
        # if we have a valid context and an existing offscreen fbo,
        # preserve the existing pixels by copying them onto the new tmp fbo (new size)
        # and then doing the gl_init() call but without initializing the offscreen fbo.
        sx, sy, dx, dy, w, h = self.gravity_copy_coords(oldw, oldh, bw, bh)
        context.update_geometry()
        # invert Y coordinates for OpenGL:
        sy = (oldh-h)-sy
        dy = (bh-h)-dy
        # re-init our OpenGL context with the new size,
        # but leave offscreen fbo with the old size
        self.gl_init(context, True)
        # copy offscreen to new tmp:
        self.copy_fbo(w, h, sx, sy, dx, dy)
        # make tmp the new offscreen:
        self.swap_fbos()
        # now we don't need the old tmp fbo contents anymore,
        # and we can re-initialize it with the correct size:
        mag_filter = self.get_init_magfilter()
        self.init_fbo(TEX_TMP_FBO, self.tmp_fbo, bw, bh, mag_filter)
        self._backing.queue_draw_area(0, 0, bw, bh)
        if FBO_RESIZE_DELAY >= 0:
            del context

            def redraw(glcontext):
                if not glcontext:
                    return
                self.pending_fbo_paint = ((0, 0, bw, bh), )
                self.do_present_fbo(glcontext)
            GLib.timeout_add(FBO_RESIZE_DELAY, self.with_gl_context, redraw)

    def gl_init_textures(self) -> None:
        log("gl_init_textures()")
        assert self.offscreen_fbo is None
        if not bool(glGenFramebuffers):
            raise RuntimeError("current context lacks framebuffer support: no glGenFramebuffers")
        self.textures = glGenTextures(N_TEXTURES)
        self.offscreen_fbo = glGenFramebuffers(1)
        self.tmp_fbo = glGenFramebuffers(1)
        log("%s.gl_init_textures() textures: %s, offscreen fbo: %s, tmp fbo: %s",
            self, self.textures, self.offscreen_fbo, self.tmp_fbo)

    def gl_init_shaders(self) -> None:
        # Create and assign fragment programs
        from OpenGL.GL import GL_FRAGMENT_SHADER, GL_VERTEX_SHADER
        vertex_shader = self.gl_init_shader("vertex", GL_VERTEX_SHADER)
        for name in ("YUV_to_RGB", "YUV_to_RGB_FULL", "NV12_to_RGB"):
            if name in self.shaders:
                continue
            fragment_shader = self.gl_init_shader(name, GL_FRAGMENT_SHADER)
            self.gl_init_program(name, vertex_shader, fragment_shader)
        self.vao = glGenVertexArrays(1)

    def gl_init_program(self, name: str, *shaders: int):
        from OpenGL.GL import (
            glAttachShader, glDetachShader,
            glCreateProgram, glDeleteProgram, glLinkProgram, glGetProgramiv, glValidateProgram, glGetShaderInfoLog,
            GL_FALSE, GL_LINK_STATUS,
        )
        program = glCreateProgram()
        for shader in shaders:
            glAttachShader(program, shader)
        glLinkProgram(program)
        infolog = glGetShaderInfoLog(shader) or "OK"
        status = glGetProgramiv(program, GL_LINK_STATUS)
        if status == GL_FALSE:
            glDeleteProgram(program)
            self.fail_shader(name, infolog)
        log(f"{name} program linked: {infolog}")
        status = glValidateProgram(program)
        infolog = glGetShaderInfoLog(shader) or "OK"
        if status == GL_FALSE:
            glDeleteProgram(program)
            self.fail_shader(name, infolog)
        log(f"{name} program validated: {infolog}")
        for shader in shaders:
            glDetachShader(program, shader)
        self.programs[name] = program

    def fail_shader(self, name: str, err: bytes):
        from OpenGL.GL import glDeleteShader
        err_str = bytestostr(err).strip("\n\r")
        shader = self.shaders.pop(name, None)
        if shader:
            glDeleteShader(shader)
        log.error(f"Error compiling {name!r} OpenGL shader:")
        for line in err_str.split("\n"):
            if line.strip():
                log.error(" %s", line.strip())
        raise RuntimeError(f"OpenGL failed to compile shader {name!r}: {nonl(err_str)}")

    def gl_init_shader(self, name, shader_type) -> int:
        # Create and assign fragment programs
        from OpenGL.GL import (
            glCreateShader, glShaderSource, glCompileShader, glGetShaderInfoLog,
            glGetShaderiv,
            GL_COMPILE_STATUS, GL_VERTEX_SHADER, GL_FRAGMENT_SHADER, GL_FALSE,
        )
        assert shader_type in (GL_VERTEX_SHADER, GL_FRAGMENT_SHADER)
        from xpra.client.gl.shaders import SOURCE
        progstr = SOURCE[name]
        shader = glCreateShader(shader_type)
        self.shaders[name] = shader
        glShaderSource(shader, progstr)
        glCompileShader(shader)
        infolog = glGetShaderInfoLog(shader) or "OK"
        status = glGetShaderiv(shader, GL_COMPILE_STATUS)
        if status == GL_FALSE:
            self.fail_shader(name, infolog)
        log(f"{name} shader initialized: {infolog}")
        return shader

    def gl_init(self, context, skip_fbo=False) -> None:
        # must be called within a context!
        # performs init if needed
        if not self.debug_setup:
            self.debug_setup = True
            context_init_debug()

        if self.gl_setup:
            return
        mt = get_max_texture_size()
        w, h = self.size
        if w > mt or h > mt:
            raise ValueError(f"invalid texture dimensions {w}x{h}, maximum size is {mt}x{mt}")
        gl_marker("Initializing GL context for window size %s, backing size %s, max texture size=%i",
                  self.render_size, self.size, mt)
        # Initialize viewport and matrices for 2D rendering
        # default is to paint to pbo, so without any scale factor or offsets
        # (as those are only applied when painting the window)
        glViewport(0, 0, w, h)

        # we don't use the depth (2D only):
        glDisable(GL_DEPTH_TEST)
        glDisable(GL_SCISSOR_TEST)
        glDisable(GL_DITHER)
        glDisable(GL_BLEND)

        if self.textures is None:
            self.gl_init_textures()

        mag_filter = self.get_init_magfilter()
        # Define empty tmp FBO
        self.init_fbo(TEX_TMP_FBO, self.tmp_fbo, w, h, mag_filter)
        if not skip_fbo:
            # Define empty FBO texture and set rendering to FBO
            self.init_fbo(TEX_FBO, self.offscreen_fbo, w, h, mag_filter)

        # Create and assign fragment programs
        self.gl_init_shaders()

        self.gl_setup = True
        log("gl_init(%s, %s) done", context, skip_fbo)

    def get_init_magfilter(self) -> IntConstant:
        rw, rh = self.render_size
        w, h = self.size
        if rw/w != rw//w or rh/h != rh//h:
            # non integer scaling, use linear magnification filter:
            return GL_LINEAR
        return GL_NEAREST

    def init_fbo(self, texture_index: int, fbo, w: int, h: int, mag_filter) -> None:
        target = GL_TEXTURE_RECTANGLE
        glBindTexture(target, self.textures[texture_index])
        # nvidia needs this even though we don't use mipmaps (repeated through this file):
        glTexParameteri(target, GL_TEXTURE_MAG_FILTER, mag_filter)
        glTexParameteri(target, GL_TEXTURE_MIN_FILTER, GL_NEAREST)
        glTexImage2D(target, 0, self.internal_format, w, h, 0, self.texture_pixel_format, GL_UNSIGNED_BYTE, None)
        glBindFramebuffer(GL_FRAMEBUFFER, fbo)
        glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, target, self.textures[texture_index], 0)

    def close_gl_config(self) -> None:
        """
        Subclasses may free up resources at this point.
        The GTK3 GL drawing area does.
        """

    def close(self) -> None:
        self.free_cuda_context()
        self.close_gl_config()
        # This seems to cause problems, so we rely
        # on destroying the context to clear textures and fbos...
        # if self.offscreen_fbo is not None:
        #    glDeleteFramebuffers(1, [self.offscreen_fbo])
        #    self.offscreen_fbo = None
        # if self.textures is not None:
        #    glDeleteTextures(self.textures)
        #    self.textures = None
        b = self._backing
        if b:
            self._backing = None
            b.destroy()
        super().close()
        from OpenGL.GL import glDeleteProgram, glDeleteShader
        programs = self.programs
        self.programs = {}
        for name, program in programs.items():
            glDeleteProgram(program)
        shaders = self.shaders
        self.shaders = {}
        for name, shader in shaders.items():
            glDeleteShader(shader)
        vao = self.vao
        if vao:
            self.vao = None
            glDeleteVertexArrays(1, [vao])


    def paint_scroll(self, scroll_data, options: typedict, callbacks: Iterable[Callable]) -> None: # pylint: disable=arguments-differ, arguments-renamed
        flush = options.intget("flush", 0)
        self.idle_add(self.with_gl_context, self.do_scroll_paints, scroll_data, flush, callbacks)

    def do_scroll_paints(self, context, scrolls, flush = 0, callbacks: Iterable[Callable] = ()) -> None:
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

        for x, y, w, h, xdelta, ydelta in scrolls:
            if abs(xdelta) >= bw:
                fail(f"invalid xdelta value: {xdelta}, backing width is {bw}")
                continue
            if abs(ydelta) >= bh:
                fail(f"invalid ydelta value: {ydelta}, backing height is {bh}")
                continue
            if ydelta == 0 and xdelta == 0:
                fail("scroll has no delta!")
                continue
            if w <= 0 or h <= 0:
                fail(f"invalid scroll area size: {w}x{h}")
                continue
            # these should be errors,
            # but desktop-scaling can cause a mismatch between the backing size
            # and the real window size server-side... so we clamp the dimensions instead
            if x+w > bw:
                w = bw-x
            if y+h > bh:
                h = bh-y
            if x+w+xdelta>bw:
                w = bw-x-xdelta
                if w <= 0:
                    continue        # nothing left!
            if y+h+ydelta>bh:
                h = bh-y-ydelta
                if h <= 0:
                    continue        # nothing left!
            if x+xdelta < 0:
                rect = (x, y, w, h)
                fail(f"horizontal scroll by {xdelta}"
                     + f" rectangle {rect} overflows the backing buffer size {self.size}")
                continue
            if y+ydelta < 0:
                rect = (x, y, w, h)
                fail(f"vertical scroll by {ydelta}"
                     + f" rectangle {rect} overflows the backing buffer size {self.size}")
                continue
            # opengl buffer is upside down, so we must invert Y coordinates: bh-(..)
            glBlitFramebuffer(x, bh-y, x+w, bh-(y+h),
                              x+xdelta, bh-(y+ydelta), x+w+xdelta, bh-(y+h+ydelta),
                              GL_COLOR_BUFFER_BIT, GL_NEAREST)
            self.paint_box("scroll", x+xdelta, y+ydelta, x+w+xdelta, y+h+ydelta)
            glFlush()

        self.swap_fbos()

        target = GL_TEXTURE_RECTANGLE
        # restore normal paint state:
        glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, target, self.textures[TEX_FBO], 0)
        glBindFramebuffer(GL_READ_FRAMEBUFFER, self.offscreen_fbo)
        glBindFramebuffer(GL_DRAW_FRAMEBUFFER, self.offscreen_fbo)
        glBindFramebuffer(GL_FRAMEBUFFER, self.offscreen_fbo)

        glBindTexture(target, 0)
        fire_paint_callbacks(callbacks, True)
        if not self.draw_needs_refresh:
            self.present_fbo(context, 0, 0, bw, bh, flush)

    def copy_fbo(self, w: int, h: int, sx = 0, sy = 0, dx = 0, dy = 0) -> None:
        log("copy_fbo%s", (w, h, sx, sy, dx, dy))
        # copy from offscreen to tmp:
        glBindFramebuffer(GL_READ_FRAMEBUFFER, self.offscreen_fbo)
        target = GL_TEXTURE_RECTANGLE
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
        # swap references to tmp and offscreen so tmp becomes the new offscreen:
        tmp = self.offscreen_fbo
        self.offscreen_fbo = self.tmp_fbo
        self.tmp_fbo = tmp
        tmp = self.textures[TEX_FBO]
        self.textures[TEX_FBO] = self.textures[TEX_TMP_FBO]
        self.textures[TEX_TMP_FBO] = tmp

    def present_fbo(self, context, x: int, y: int, w: int, h: int, flush=0) -> None:
        log("present_fbo: adding %s to pending paint list (size=%i), flush=%s, paint_screen=%s",
            (x, y, w, h), len(self.pending_fbo_paint), flush, self.paint_screen)
        if not context:
            raise RuntimeError("missing OpenGL paint context")
        self.pending_fbo_paint.append((x, y, w, h))
        if not self.paint_screen:
            return
        # flush>0 means we should wait for the final flush=0 paint
        if flush == 0 or not PAINT_FLUSH:
            self.record_fps_event()
            self.managed_present_fbo(context)

    def managed_present_fbo(self, context) -> None:
        if not context:
            raise RuntimeError("missing opengl paint context")
        try:
            with paint_context_manager:
                self.do_present_fbo(context)
        except Exception as e:
            log.error("Error presenting FBO:")
            log.estr(e)
            log("Error presenting FBO", exc_info=True)
            self.last_present_fbo_error = str(e)

    def do_present_fbo(self, context) -> None:
        bw, bh = self.size
        rect_count = len(self.pending_fbo_paint)
        if self.is_double_buffered() or self.size!=self.render_size:
            # refresh the whole window:
            rectangles = ((0, 0, bw, bh), )
        else:
            # paint just the rectangles we have accumulated:
            rectangles = self.pending_fbo_paint
        self.pending_fbo_paint = []

        if SAVE_BUFFERS:
            self.save_fbo()

        gl_marker("presenting FBO on screen, rectangles=%s", rectangles)
        # Change state to target screen instead of our FBO
        glBindFramebuffer(GL_FRAMEBUFFER, 0)
        glBindFramebuffer(GL_DRAW_FRAMEBUFFER, 0)

        # viewport for clearing the whole window:
        ww, wh = self.render_size
        scale = context.get_scale_factor()
        left, top, right, bottom = self.offsets
        glViewport(0, 0, int((left+ww+right)*scale), int((top+wh+bottom)*scale))
        if left or top or right or bottom:
            if self._alpha_enabled:
                # transparent background:
                glClearColor(0.0, 0.0, 0.0, 0.0)
            else:
                # black, no alpha:
                glClearColor(0.0, 0.0, 0.0, 1.0)
            glClear(GL_COLOR_BUFFER_BIT)

        # from now on, take the offsets and scaling into account:
        viewport = int(left*scale), int(top*scale), int(ww*scale), int(wh*scale)
        log(f"window viewport for {self.render_size=} and {self.offsets} with scale factor {scale}: {viewport}")
        glViewport(*viewport)
        target = GL_TEXTURE_RECTANGLE
        if ww != bw or wh != bh or scale != 1:
            glTexParameteri(target, GL_TEXTURE_MAG_FILTER, GL_LINEAR)
            glTexParameteri(target, GL_TEXTURE_MIN_FILTER, GL_LINEAR)

        # Draw FBO texture on screen
        glBindTexture(target, self.textures[TEX_FBO])

        glBindFramebuffer(GL_READ_FRAMEBUFFER, self.offscreen_fbo)
        glFramebufferTexture2D(GL_READ_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, target, self.textures[TEX_FBO], 0)
        glReadBuffer(GL_COLOR_ATTACHMENT0)

        glBindFramebuffer(GL_DRAW_FRAMEBUFFER, 0)

        for x, y, w, h in rectangles:
            glBlitFramebuffer(x, y, w, h,
                              x, y, w, h,
                              GL_COLOR_BUFFER_BIT, GL_NEAREST)
        glBindTexture(target, 0)

        if self.pointer_overlay:
            self.draw_pointer()

        if self.paint_spinner:
            self.draw_spinner()

        if self.border and self.border.shown:
            self.draw_border()

        if self.is_show_fps():
            self.draw_fps()

        # Show the backbuffer on screen
        glFlush()
        self.gl_show(rect_count)
        gl_frame_terminator()

        # restore pbo viewport
        glViewport(0, 0, bw, bh)
        glTexParameteri(target, GL_TEXTURE_MAG_FILTER, GL_NEAREST)
        glTexParameteri(target, GL_TEXTURE_MIN_FILTER, GL_NEAREST)
        glBindFramebuffer(GL_FRAMEBUFFER, self.offscreen_fbo)
        log("%s.do_present_fbo() done", self)

    def save_fbo(self) -> None:
        width, height = self.size
        save_fbo(self.wid, self.offscreen_fbo, self.textures[TEX_FBO], width, height, self._alpha_enabled)

    def draw_pointer(self) -> None:
        px, py, _, _, size, start_time = self.pointer_overlay
        elapsed = monotonic()-start_time
        log("pointer_overlay=%s, elapsed=%.1f, timeout=%s, cursor-data=%s",
            self.pointer_overlay, elapsed, CURSOR_IDLE_TIMEOUT, (self.cursor_data or [])[:7])
        if elapsed>=CURSOR_IDLE_TIMEOUT:
            # timeout - stop showing it:
            self.pointer_overlay = None
            return
        x = px
        y = py
        if not self.cursor_data:
            # paint a fake one:
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

    def blend_texture(self, texture, x: int, y: int, w: int, h: int) -> None:
        # paint this texture
        glActiveTexture(GL_TEXTURE0)
        target = GL_TEXTURE_RECTANGLE
        glEnable(target)
        glBindTexture(target, texture)
        glEnable(GL_BLEND)
        glBlendFunc(GL_ONE, GL_ONE_MINUS_SRC_ALPHA)
        # glTexEnvi(GL_TEXTURE_ENV, GL_TEXTURE_ENV_MODE, GL_REPLACE)

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
        rgba = tuple(round(v*256) for v in (self.border.red, self.border.green, self.border.blue, self.border.alpha))

        # render to screen:
        glBindFramebuffer(GL_DRAW_FRAMEBUFFER, 0)

        self.draw_rectangle(0, 0, bw, bh, self.border.size, *rgba)

    def paint_box(self, encoding : str, x: int, y: int, w: int, h: int) -> None:
        # show region being painted if debug paint box is enabled only:
        if self.paint_box_line_width <= 0:
            return
        # render to offscreen fbo:
        target = GL_TEXTURE_RECTANGLE
        glBindFramebuffer(GL_DRAW_FRAMEBUFFER, self.offscreen_fbo)
        glBindTexture(target, self.textures[TEX_FBO])
        glFramebufferTexture2D(GL_DRAW_FRAMEBUFFER, GL_COLOR_ATTACHMENT1, target, self.textures[TEX_FBO], 0)
        glDrawBuffer(GL_COLOR_ATTACHMENT1)

        bw, bh = self.size
        glViewport(0, 0, bw, bh)

        color = get_paint_box_color(encoding)
        rgba = tuple(round(v*256) for v in color)
        self.draw_rectangle(x, y, w, h, self.paint_box_line_width, *rgba)

    def draw_rectangle(self, x: int, y: int, w: int, h: int, size=1, red=0, green=0, blue=0, alpha=0) -> None:
        log("draw_rectangle%s", (x, y, w, h, size, red, green, blue, alpha))
        rgba = tuple(max(0, min(255, v)) for v in (red, green, blue, alpha))
        pixel = struct.pack(b"!BBBB", *rgba)
        texture = int(self.textures[TEX_RGB])
        glActiveTexture(GL_TEXTURE0)
        upload_rgba_texture(texture, 1, 1, pixel)

        # set fbo with rgb texture as framebuffer source:
        target = GL_TEXTURE_RECTANGLE
        glBindFramebuffer(GL_READ_FRAMEBUFFER, self.tmp_fbo)
        glFramebufferTexture2D(GL_READ_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, target, texture, 0)
        glReadBuffer(GL_COLOR_ATTACHMENT0)

        # invert y screen coordinates:
        bh = self.size[1]

        for rx, ry, rw, rh in (
                (x, y, size, h),
                (x+w-size, y, size, h),
                (x+size, y, w-2*size, size),
                (x+size, y+h-size, w-2*size, size),
        ):
            glBlitFramebuffer(0, 0, 1, 1,
                              rx, bh-ry, rx + rw, bh-(ry + rh),
                              GL_COLOR_BUFFER_BIT, GL_NEAREST)

    def update_fps_buffer(self, width, height, pixels) -> None:
        # we always call 'record_fps_event' from a gl context,
        # so it is safe to upload the texture:
        texture = int(self.textures[TEX_FPS])
        glActiveTexture(GL_TEXTURE0)
        upload_rgba_texture(texture, width, height, pixels)

    def draw_fps(self) -> None:
        x, y = 2, 5
        width, height = self.fps_buffer_size
        return
        self.blend_texture(self.textures[TEX_FPS], x, y, width, height)
        self.cancel_fps_refresh()

        def refresh_screen(context):
            self.fps_refresh_timer = 0
            log("refresh_screen(%s)", context)
            if not self.paint_screen:
                return
            if context:
                self.update_fps()
                self.managed_present_fbo(context)
        self.fps_refresh_timer = GLib.timeout_add(1000, self.with_gl_context, refresh_screen)

    def validate_cursor(self) -> bool:
        cursor_data = self.cursor_data
        cw: int = cursor_data[3]
        ch: int = cursor_data[4]
        pixels = cursor_data[8]
        blen = cw*ch*4
        if len(pixels)!=blen:
            log.error("Error: invalid cursor pixel buffer for %ix%i", cw, ch)
            log.error(" expected %i bytes but got %i (%s)", blen, len(pixels), type(pixels))
            log.error(" %s", repr_ellipsized(hexstr(pixels)))
            return False
        return True

    def set_cursor_data(self, cursor_data) -> None:
        if not cursor_data or cursor_data[0] is None:
            # use the default cursor
            if not self.default_cursor_data:
                return
            cursor_data = list(self.default_cursor_data)
        self.cursor_data = cursor_data
        if not self.validate_cursor():
            return
        cw = cursor_data[3]
        ch = cursor_data[4]
        pixels = cursor_data[8]

        def gl_upload_cursor(context):
            if context:
                self.gl_init(context)
                texture = int(self.textures[TEX_CURSOR])
                glActiveTexture(GL_TEXTURE0)
                upload_rgba_texture(texture, cw, ch, pixels)
        self.with_gl_context(gl_upload_cursor)

    def paint_jpeg(self, img_data, x: int, y: int, width: int, height: int,
                   options: typedict, callbacks: Iterable[Callable]) -> None:
        self.do_paint_jpeg("jpeg", img_data, x, y, width, height, options, callbacks)

    def paint_jpega(self, img_data, x: int, y: int, width: int, height: int,
                    options: typedict, callbacks: Iterable[Callable]) -> None:
        self.do_paint_jpeg("jpega", img_data, x, y, width, height, options, callbacks)

    def do_paint_jpeg(self, encoding, img_data, x: int, y: int, width: int, height: int,
                      options: typedict, callbacks: Iterable[Callable]) -> None:
        if width >= 16 and height >= 16:
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
            self.idle_add(self.gl_paint_planar, "YUV_to_RGB_FULL", flush, encoding, img,
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

    def cuda_buffer_to_pbo(self, gl_context, cuda_buffer, rowstride: int, src_y: int, height: int, stream):
        # must be called with an active cuda context, and from the UI thread
        self.gl_init(gl_context)
        pbo = glGenBuffers(1)
        size = rowstride*height
        glBindBuffer(GL_PIXEL_UNPACK_BUFFER, pbo)
        glBufferData(GL_PIXEL_UNPACK_BUFFER, size, None, GL_STREAM_DRAW)
        glBindBuffer(GL_PIXEL_UNPACK_BUFFER, 0)
        # pylint: disable=import-outside-toplevel
        from pycuda.driver import Memcpy2D   # pylint: disable=no-name-in-module
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

    def paint_nvdec(self, gl_context, encoding, img_data, x: int, y: int, width: int, height: int,
                    options: typedict, callbacks: Iterable[Callable]) -> None:
        with self.assign_cuda_context(True):
            # we can import pycuda safely here,
            # because `self.assign_cuda_context` will have imported it with the lock:
            from pycuda.driver import Stream, LogicError  # @UnresolvedImport pylint: disable=import-outside-toplevel
            stream = Stream()
            options["stream"] = stream
            img = self.nvdec_decoder.decompress_with_device(encoding, img_data, width, height, options)
            log("paint_nvdec: gl_context=%s, img=%s, downloading buffer to pbo", gl_context, img)
            pixel_format = img.get_pixel_format()
            if pixel_format not in ("NV12", ):
                raise ValueError(f"unexpected pixel format {pixel_format}")
            # `pixels` is a cuda buffer with 2 planes: Y then UV
            cuda_buffer = img.get_pixels()
            strides = img.get_rowstride()
            height = img.get_height()
            try:
                y_pbo = self.cuda_buffer_to_pbo(gl_context, cuda_buffer, strides[0], 0, height, stream)
                uv_pbo = self.cuda_buffer_to_pbo(gl_context, cuda_buffer, strides[1], roundup(height, 2), height//2, stream)
            except LogicError as e:
                # disable nvdec from now on:
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
        self.do_gl_paint_planar(gl_context, "NV12_to_RGB", flush, encoding, img,
                                x, y, w, h, width, height,
                                options, callbacks)

    def paint_nvjpeg(self, gl_context, encoding, img_data, x: int, y: int, width: int, height: int,
                     options: typedict, callbacks: Iterable[Callable]) -> None:
        with self.assign_cuda_context(True):
            # we can import pycuda safely here,
            # because `self.assign_cuda_context` will have imported it with the lock:
            from pycuda.driver import Stream  # @UnresolvedImport pylint: disable=import-outside-toplevel
            stream = Stream()
            options["stream"] = stream
            img = self.nvjpeg_decoder.decompress_with_device("RGB", img_data, options)
            log("paint_nvjpeg: gl_context=%s, img=%s, downloading buffer to pbo", gl_context, img)
            rgb_format = img.get_pixel_format()
            if rgb_format not in ("RGB", "BGR", "RGBA", "BGRA"):
                raise ValueError(f"unexpected rgb format {rgb_format}")
            # `pixels` is a cuda buffer:
            cuda_buffer = img.get_pixels()
            pbo = self.cuda_buffer_to_pbo(gl_context, cuda_buffer, img.get_rowstride(), 0, img.get_height(), stream)
            cuda_buffer.free()

        pformat = PIXEL_FORMAT_TO_CONSTANT[rgb_format]
        target = GL_TEXTURE_RECTANGLE
        glBindTexture(target, self.textures[TEX_RGB])
        glBindBuffer(GL_PIXEL_UNPACK_BUFFER, pbo)
        glPixelStorei(GL_UNPACK_ROW_LENGTH, 0)
        glPixelStorei(GL_UNPACK_ALIGNMENT, 1)
        glTexImage2D(target, 0, self.internal_format, width, height, 0, pformat, GL_UNSIGNED_BYTE, None)
        glBindBuffer(GL_PIXEL_UNPACK_BUFFER, 0)

        set_alignment(width, width*len(rgb_format), rgb_format)

        glBindFramebuffer(GL_READ_FRAMEBUFFER, self.tmp_fbo)
        glFramebufferTexture2D(GL_READ_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, target, self.textures[TEX_RGB], 0)
        glReadBuffer(GL_COLOR_ATTACHMENT0)

        glBindFramebuffer(GL_DRAW_FRAMEBUFFER, self.offscreen_fbo)
        glBindTexture(target, self.textures[TEX_FBO])
        glFramebufferTexture2D(GL_DRAW_FRAMEBUFFER, GL_COLOR_ATTACHMENT1, target, self.textures[TEX_FBO], 0)
        glDrawBuffer(GL_COLOR_ATTACHMENT1)

        rh = self.render_size[1]
        glBlitFramebuffer(0, 0, width, height,
                          x, rh - y, x + width, rh - y - height,
                          GL_COLOR_BUFFER_BIT, GL_NEAREST)

        glBindTexture(target, 0)

        self.paint_box(encoding, x, y, width, height)
        # Present update to screen
        if not self.draw_needs_refresh:
            self.present_fbo(gl_context, x, y, width, height, options.intget("flush", 0))
        # present_fbo has reset state already
        fire_paint_callbacks(callbacks)
        glDeleteBuffers(1, [pbo])

    def paint_webp(self, img_data, x: int, y: int, width: int, height: int,
                   options: typedict, callbacks: Iterable[Callable]) -> None:
        subsampling = options.strget("subsampling")
        has_alpha = options.boolget("has_alpha")
        if subsampling=="YUV420P" and WEBP_YUV and self.webp_decoder and not WEBP_PILLOW and not has_alpha and width>=2 and height>=2:
            img = self.webp_decoder.decompress_yuv(img_data)
            flush = options.intget("flush", 0)
            w = img.get_width()
            h = img.get_height()
            self.idle_add(self.gl_paint_planar, "YUV_to_RGB", flush, "webp", img,
                          x, y, w, h, width, height, options, callbacks)
            return
        super().paint_webp(img_data, x, y, width, height, options, callbacks)

    def paint_avif(self, img_data, x:int, y:int, width:int, height:int,
                   options: typedict, callbacks: Iterable[Callable]) -> None:
        alpha = options.boolget("alpha")
        img = self.avif_decoder.decompress(img_data, options, yuv=not alpha)
        pixel_format = img.get_pixel_format()
        flush = options.intget("flush", 0)
        w = img.get_width()
        h = img.get_height()
        if pixel_format.startswith("YUV"):
            self.idle_add(self.gl_paint_planar, "YUV_to_RGB_FULL", flush, "avif", img,
                          x, y, w, h, width, height, options, callbacks)
        else:
            self.idle_add(self.do_paint_rgb, pixel_format, img.get_pixels(), x, y, w, h, width, height,
                          img.get_rowstride(), options, callbacks)

    def do_paint_rgb(self, rgb_format: str, img_data,
                     x: int, y: int, width: int, height: int, render_width: int, render_height: int, rowstride: int,
                     options: typedict, callbacks: Iterable[Callable]) -> None:
        self.with_gl_context(self.gl_paint_rgb,
                             rgb_format, img_data,
                             x, y, width, height,
                             render_width, render_height, rowstride, options, callbacks)

    def gl_paint_rgb(self, context, rgb_format: str, img_data,
                     x: int, y: int, width: int, height: int, render_width: int, render_height: int, rowstride: int,
                     options: typedict, callbacks : Iterable[Callable]):
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
        try:
            upload, img_data = pixels_for_upload(img_data)

            self.gl_init(context)
            scaling = width != render_width or height != render_height

            # convert it to a GL constant:
            pformat = PIXEL_FORMAT_TO_CONSTANT.get(rgb_format)
            if pformat is None:
                raise ValueError(f"could not find pixel format for {rgb_format!r}")
            ptype = PIXEL_UPLOAD_FORMAT.get(rgb_format)
            if pformat is None:
                raise ValueError(f"could not find pixel type for {rgb_format!r}")

            gl_marker("%s update at (%d,%d) size %dx%d (%s bytes) to %dx%d, using GL %s format=%s / %s to internal format=%s",
                      rgb_format, x, y, width, height, len(img_data), render_width, render_height,
                      upload, CONSTANT_TO_PIXEL_FORMAT.get(pformat), DATATYPE_TO_STR.get(ptype),
                      INTERNAL_FORMAT_TO_STR.get(self.internal_format)
                      )

            # Upload data as temporary RGB texture
            target = GL_TEXTURE_RECTANGLE
            glBindTexture(target, self.textures[TEX_RGB])
            set_alignment(width, rowstride, rgb_format)
            mag_filter = GL_NEAREST
            if scaling:
                mag_filter = GL_LINEAR
            glTexParameteri(target, GL_TEXTURE_MAG_FILTER, mag_filter)
            glTexParameteri(target, GL_TEXTURE_MIN_FILTER, GL_NEAREST)
            glTexParameteri(target, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_BORDER)
            glTexParameteri(target, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_BORDER)
            glTexImage2D(target, 0, self.internal_format, width, height, 0, pformat, ptype, img_data)

            glBindFramebuffer(GL_READ_FRAMEBUFFER, self.tmp_fbo)
            glFramebufferTexture2D(GL_READ_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, target, self.textures[TEX_RGB], 0)
            glReadBuffer(GL_COLOR_ATTACHMENT0)

            glBindFramebuffer(GL_DRAW_FRAMEBUFFER, self.offscreen_fbo)
            glBindTexture(target, self.textures[TEX_FBO])
            glFramebufferTexture2D(GL_DRAW_FRAMEBUFFER, GL_COLOR_ATTACHMENT1, target, self.textures[TEX_FBO], 0)
            glDrawBuffer(GL_COLOR_ATTACHMENT1)

            rh = self.render_size[1]
            glBlitFramebuffer(0, 0, width, height,
                              x, rh-y, x + render_width, rh - y - render_height,
                              GL_COLOR_BUFFER_BIT, GL_NEAREST)

            glBindTexture(target, 0)

            self.paint_box(options.strget("encoding", ""), x, y, render_width, render_height)
            # Present update to screen
            if not self.draw_needs_refresh:
                self.present_fbo(context, x, y, render_width, render_height, options.intget("flush", 0))
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
                       x: int, y: int, enc_width: int, enc_height: int, width: int, height: int,
                       options, callbacks: Iterable[Callable]):
        log("do_video_paint%s", (x, y, enc_width, enc_height, width, height, options, callbacks))
        if not zerocopy_upload or FORCE_CLONE:
            # copy so the data will be usable (usually a str)
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
            # call superclass to handle csc
            # which will end up calling paint rgb with r210 data
            super().do_video_paint(img, x, y, enc_width, enc_height, width, height, options, callbacks)
            return
        shader = "NV12_to_RGB" if pixel_format == "NV12" else "YUV_to_RGB"
        self.idle_add(self.gl_paint_planar, shader, options.intget("flush", 0), options.strget("encoding"), img,
                      x, y, enc_width, enc_height, width, height, options, callbacks)

    def gl_paint_planar(self, shader: str, flush: int, encoding: str, img,
                        x: int, y: int, enc_width: int, enc_height: int, width: int, height: int,
                        options: typedict, callbacks: Iterable[Callable]):
        # this function runs in the UI thread, no video_decoder lock held
        log("gl_paint_planar%s", (flush, encoding, img, x, y, enc_width, enc_height, width, height, options, callbacks))
        self.with_gl_context(self.do_gl_paint_planar, shader, flush, encoding, img,
                             x, y, enc_width, enc_height,
                             width, height, options, callbacks)

    def do_gl_paint_planar(self, context, shader: str, flush: int, encoding: str, img,
                           x: int, y: int, enc_width: int, enc_height: int, width: int, height: int,
                           options: typedict, callbacks: Iterable[Callable]):
        x, y = self.gravity_adjust(x, y, options)
        try:
            pixel_format = img.get_pixel_format()
            if pixel_format not in ("YUV420P", "YUV422P", "YUV444P", "GBRP", "NV12", "GBRP16", "YUV444P16"):
                raise ValueError(f"the GL backing does not handle pixel format {pixel_format!r} yet!")
            if not context:
                log("%s._do_paint_rgb(..) no OpenGL context!", self)
                fire_paint_callbacks(callbacks, False, "failed to get a gl context")
                return
            self.gl_init(context)
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
                self.present_fbo(context, x, y, width, height, flush)
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

    def update_planar_textures(self, width: int, height: int, img, pixel_format, scaling=False, pbo=False):
        assert self.textures is not None, "no OpenGL textures!"
        upload_formats = PIXEL_UPLOAD_FORMAT[pixel_format]
        internal_formats = PIXEL_INTERNAL_FORMAT.get(pixel_format, (GL_R8, GL_R8, GL_R8))
        data_formats = PIXEL_DATA_FORMAT.get(pixel_format, (GL_RED, GL_RED, GL_RED))
        divs = get_subsampling_divs(pixel_format)
        bytespp = 2 if (pixel_format.endswith("P16") or pixel_format.endswith("P10")) else 1
        # textures: usually 3, but only 2 for "NV12"
        textures = (
            (GL_TEXTURE0, TEX_Y),
            (GL_TEXTURE1, TEX_U),
            (GL_TEXTURE2, TEX_V),
            )[:len(divs)]
        log("%s.update_planar_textures%s textures=%s", self, (width, height, img, pixel_format, scaling, pbo), textures)
        if self.pixel_format!=pixel_format or self.texture_size!=(width, height):
            gl_marker("Creating new planar textures, pixel format %s (was %s), texture size %s (was %s)",
                      pixel_format, self.pixel_format, (width, height), self.texture_size)
            self.pixel_format = pixel_format
            self.texture_size = (width, height)
            # Create textures of the same size as the window's
            target = GL_TEXTURE_RECTANGLE
            for texture, index in textures:
                (div_w, div_h) = divs[index]
                glActiveTexture(texture)
                glBindTexture(target, self.textures[index])
                mag_filter = GL_NEAREST
                if scaling or (div_w > 1 or div_h > 1):
                    mag_filter = GL_LINEAR
                glTexParameteri(target, GL_TEXTURE_MAG_FILTER, mag_filter)
                glTexParameteri(target, GL_TEXTURE_MIN_FILTER, GL_NEAREST)

                iformat = internal_formats[index]
                dformat = data_formats[index]
                uformat = upload_formats[index]     # upload format: ie: UNSIGNED_BYTE
                glTexImage2D(target, 0, iformat, width//div_w, height//div_h, 0, dformat, uformat, None)
                # glBindTexture(target, 0)        #redundant: we rebind below:

        gl_marker("updating planar textures: %sx%s %s", width, height, pixel_format)
        rowstrides = img.get_rowstride()
        img_data = img.get_pixels()
        if len(rowstrides)!=len(divs) or len(img_data)!=len(divs):
            raise RuntimeError(f"invalid number of planes for {pixel_format}")
        for texture, index in textures:
            # "YUV420P" -> ("Y", "U", "V")
            # "GBRP16" -> ("GG", "BB", "RR")
            # "NV12" -> ("Y", "UV")
            tex_name = get_plane_name(pixel_format, index) * bytespp
            dformat = data_formats[index]       #data format: ie: GL_RED
            uformat = upload_formats[index]     #upload format: ie: UNSIGNED_BYTE
            rowstride = rowstrides[index]
            div_w, div_h = divs[index]
            w = width//div_w
            if dformat==GL_LUMINANCE_ALPHA:
                # uploading 2 components
                w //= 2
            elif dformat not in (GL_RED, GL_LUMINANCE):
                raise RuntimeError(f"unexpected data format {dformat} for {pixel_format}")
            h = height//div_h
            if w == 0 or h == 0:
                log.error(f"Error: zero dimension {w}x{h} for {pixel_format} planar texture {tex_name}")
                log.error(f" screen update {width}x{height} dropped, div={div_w}x{div_h}")
                continue
            glActiveTexture(texture)

            target = GL_TEXTURE_RECTANGLE
            glBindTexture(target, self.textures[index])
            set_alignment(w, rowstride, tex_name)
            plane = img_data[index]
            if pbo:
                upload = "pbo"
                glBindBuffer(GL_PIXEL_UNPACK_BUFFER, plane)
                pixel_data = None
                size = rowstride*h
            else:
                upload, pixel_data = pixels_for_upload(plane)
                size = len(pixel_data)
            glTexParameteri(target, GL_TEXTURE_BASE_LEVEL, 0)
            try:
                glTexParameteri(target, GL_TEXTURE_MAX_LEVEL, 0)
            except GLError:
                pass
            log(f"texture {index}: {tex_name:2} div={div_w},{div_h}, rowstride={rowstride}, {w}x{h}, "+
                f"data={size} bytes, upload={upload}, format={dformat}, type={uformat}")
            glTexSubImage2D(target, 0, 0, 0, w, h, dformat, uformat, pixel_data)
            glBindTexture(target, 0)
            glBindBuffer(GL_PIXEL_UNPACK_BUFFER, 0)
        # glActiveTexture(GL_TEXTURE0)    #redundant, we always call render_planar_update afterwards

    def render_planar_update(self, rx: int, ry: int, rw: int, rh: int, x_scale=1.0, y_scale=1.0, shader="YUV_to_RGB"):
        log("%s.render_planar_update%s pixel_format=%s",
            self, (rx, ry, rw, rh, x_scale, y_scale, shader), self.pixel_format)
        if self.pixel_format not in ("YUV420P", "YUV422P", "YUV444P", "GBRP", "NV12", "GBRP16", "YUV444P16"):
            # not ready to render yet
            return
        divs = get_subsampling_divs(self.pixel_format)
        textures = (
            (GL_TEXTURE0, TEX_Y),
            (GL_TEXTURE1, TEX_U),
            (GL_TEXTURE2, TEX_V),
            )[:len(divs)]
        gl_marker("painting planar update, format %s", self.pixel_format)

        target = GL_TEXTURE_RECTANGLE
        glBindFramebuffer(GL_DRAW_FRAMEBUFFER, self.offscreen_fbo)
        glBindTexture(target, self.textures[TEX_FBO])
        glFramebufferTexture2D(GL_DRAW_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, target, self.textures[TEX_FBO], 0)
        glDrawBuffer(GL_COLOR_ATTACHMENT0)

        ww, wh = self.render_size
        # the region we're updating:
        glViewport(rx, wh-ry-rh, rw, rh)

        program = self.programs[shader]
        glUseProgram(program)
        for texture, index in textures:
            glActiveTexture(texture)
            glBindTexture(target, self.textures[index])
            plane_name = shader[index:index+1]        #ie: "YUV_to_RGB"  0 -> "Y"
            tex_loc = glGetUniformLocation(program, plane_name)   #ie: "Y" -> 0
            glUniform1i(tex_loc, index)         # tell the shader where to find the texture: 0 -> TEXTURE_0

        vertices = [x for x in [
            -1, -1, 1, -1, -1, 1, 1, 1,
        ]]
        c_vertices = (c_float * len(vertices))(*vertices)
        # no need to call glGetAttribLocation(program, "position")
        # since we specify the location in the shader:
        position = 0

        viewport_pos = glGetUniformLocation(program, "viewport_pos")
        if viewport_pos >= 0:
            glUniform2f(viewport_pos, rx, ry)

        glBindVertexArray(self.vao)
        pos_buffer = glGenBuffers(1)
        glBindBuffer(GL_ARRAY_BUFFER, pos_buffer)
        glBufferData(GL_ARRAY_BUFFER, len(vertices)*4, c_vertices, GL_STATIC_DRAW)
        glVertexAttribPointer(position, 2, GL_FLOAT, GL_FALSE, 0, c_void_p(0))
        glBindBuffer(GL_ARRAY_BUFFER, 0)
        glEnableVertexAttribArray(position)

        glDrawArrays(GL_TRIANGLE_STRIP, 0, 4)

        glDeleteBuffers(1, [pos_buffer])
        glDisableVertexAttribArray(position)
        glBindVertexArray(0)
        glUseProgram(0)
        for texture, index in textures:
            glActiveTexture(texture)
            glBindTexture(target, 0)
        glActiveTexture(GL_TEXTURE0)

    def gl_show(self, rect_count: int) -> None:
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
                self.gl_init(context)
                self.present_fbo(context, *rect)
        self.with_gl_context(expose)
