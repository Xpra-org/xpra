# This file is part of Xpra.
# Copyright (C) 2013 Serviware (Arthur Huillet, <ahuillet@serviware.com>)
# Copyright (C) 2012 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import struct
from time import monotonic
from typing import Any
from math import sin, pi
from ctypes import c_float, c_void_p
from collections.abc import Callable, Sequence
from contextlib import AbstractContextManager, nullcontext

from OpenGL.error import GLError
from OpenGL.constant import IntConstant
from OpenGL.GL import (
    GLuint, glGetIntegerv,
    GL_VIEWPORT,
    GL_PIXEL_UNPACK_BUFFER, GL_STREAM_DRAW,
    GL_UNPACK_ROW_LENGTH, GL_UNPACK_ALIGNMENT,
    GL_TEXTURE_MAG_FILTER, GL_TEXTURE_MIN_FILTER, GL_NEAREST,
    GL_UNSIGNED_BYTE, GL_UNSIGNED_SHORT,
    GL_LINEAR, GL_RED, GL_R8, GL_R16, GL_LUMINANCE, GL_LUMINANCE_ALPHA,
    GL_TEXTURE0, GL_TEXTURE1, GL_TEXTURE2, GL_TEXTURE3, GL_COLOR_BUFFER_BIT,
    GL_TEXTURE_WRAP_S, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_BORDER,
    GL_DEPTH_TEST, GL_SCISSOR_TEST, GL_DITHER,
    GL_RGB, GL_RGBA, GL_BGR, GL_BGRA, GL_RGBA8, GL_RGB8, GL_RGB10_A2, GL_RGB565, GL_RGB5_A1, GL_RGBA4, GL_RGBA16,
    GL_UNSIGNED_INT_2_10_10_10_REV, GL_UNSIGNED_INT_10_10_10_2, GL_UNSIGNED_SHORT_5_6_5,
    GL_BLEND,
    GL_TEXTURE_MAX_LEVEL, GL_TEXTURE_BASE_LEVEL,
    glActiveTexture, glTexSubImage2D,
    glViewport,
    glGenTextures, glDeleteTextures,
    glDisable,
    glBindTexture, glPixelStorei, glFlush,
    glBindBuffer, glGenBuffers, glBufferData, glDeleteBuffers,
    glTexParameteri,
    glTexImage2D,
    glClear, glClearColor,
    glDrawBuffer, glReadBuffer,
    GL_FLOAT, GL_ARRAY_BUFFER,
    GL_STATIC_DRAW, GL_FALSE,
    glDrawArrays, GL_TRIANGLE_STRIP, GL_TRIANGLES,
    glEnableVertexAttribArray, glVertexAttribPointer, glDisableVertexAttribArray,
    glGenVertexArrays, glBindVertexArray, glDeleteVertexArrays,
    glUseProgram, GL_TEXTURE_RECTANGLE, glGetUniformLocation, glUniform1i, glUniform1f, glUniform2f, glUniform4f,
)
from OpenGL.GL.ARB.framebuffer_object import (
    GL_FRAMEBUFFER, GL_DRAW_FRAMEBUFFER, GL_READ_FRAMEBUFFER,
    GL_COLOR_ATTACHMENT0, GL_COLOR_ATTACHMENT1,
    glGenFramebuffers, glDeleteFramebuffers, glBindFramebuffer, glFramebufferTexture2D, glBlitFramebuffer,
)

from xpra.os_util import gi_import
from xpra.util.str_fn import repr_ellipsized, hexstr, csv
from xpra.util.env import envint, envbool, first_time
from xpra.util.objects import typedict
from xpra.util.system import is_X11
from xpra.common import roundup, PaintCallbacks
from xpra.codecs.constants import get_subsampling_divs, get_plane_name
from xpra.client.gui.window_border import WindowBorder
from xpra.client.gui.paint_colors import get_paint_box_color
from xpra.client.gui.window.backing import fire_paint_callbacks, WindowBackingBase, WEBP_PILLOW, ALERT_MODE
from xpra.opengl.check import GL_ALPHA_SUPPORTED, get_max_texture_size
from xpra.opengl.debug import context_init_debug, gl_marker, gl_frame_terminator
from xpra.opengl.util import (
    save_fbo, SAVE_BUFFERS,
    zerocopy_upload, pixels_for_upload, set_alignment, upload_rgba_texture,
)
from xpra.log import Logger

log = Logger("opengl", "paint")
fpslog = Logger("opengl", "fps")

GLib = gi_import("GLib")

OPENGL_DEBUG = envbool("XPRA_OPENGL_DEBUG", False)
PAINT_FLUSH = envbool("XPRA_PAINT_FLUSH", True)
JPEG_YUV = envbool("XPRA_JPEG_YUV", True)
WEBP_YUV = envint("XPRA_WEBP_YUV", 1)
FORCE_CLONE = envbool("XPRA_OPENGL_FORCE_CLONE", False)
FORCE_VIDEO_PIXEL_FORMAT = os.environ.get("XPRA_FORCE_VIDEO_PIXEL_FORMAT", "")
DRAW_REFRESH = envbool("XPRA_OPENGL_DRAW_REFRESH", True)
FBO_RESIZE = envbool("XPRA_OPENGL_FBO_RESIZE", True)
FBO_RESIZE_DELAY = envint("XPRA_OPENGL_FBO_RESIZE_DELAY", -1)
CONTEXT_REINIT = envbool("XPRA_OPENGL_CONTEXT_REINIT", False)
NVJPEG = envbool("XPRA_OPENGL_NVJPEG", True)
NVDEC = envbool("XPRA_OPENGL_NVDEC", False)
ALWAYS_RGBA = envbool("XPRA_OPENGL_ALWAYS_RGBA", False)
SHOW_PLANE_RANGES = envbool("XPRA_SHOW_PLANE_RANGES", False)

CURSOR_IDLE_TIMEOUT: int = envint("XPRA_CURSOR_IDLE_TIMEOUT", 6)

PLANAR_FORMATS = (
    "YUV420P", "YUV422P", "YUV444P", "NV12",
    "YUV420P16", "YUV422P16", "YUV444P16",
    "YUVA420P", "YUVA422P", "YUVA444P",
    "GBRP", "GBRP16",
)

PIXEL_FORMAT_TO_CONSTANT: dict[str, IntConstant] = {
    "r210": GL_BGRA,
    "R210": GL_RGBA,
    "BGR": GL_BGR,
    "RGB": GL_RGB,
    "BGRA": GL_BGRA,
    "BGRX": GL_BGRA,
    "RGBA": GL_RGBA,
    "RGBX": GL_RGBA,
    "BGR565": GL_RGB,
    "RGB565": GL_RGB,
}
PIXEL_INTERNAL_FORMAT: dict[str, Sequence[IntConstant]] = {
    # defaults to: GL_R8, GL_R8, GL_R8, GL_R8
    # (meaning: up to 4 planes, 8 bits each)
    # override for formats that use 16 bit per channel:
    "NV12": (GL_LUMINANCE, GL_LUMINANCE_ALPHA),
    "GBRP": (GL_LUMINANCE, GL_LUMINANCE, GL_LUMINANCE),  # invalid according to the spec! (only value that works)
    "GBRP16": (GL_R16, GL_R16, GL_R16),
    "YUV444P10": (GL_R16, GL_R16, GL_R16),
    "YUV420P16": (GL_R16, GL_R16, GL_R16),
    "YUV422P16": (GL_R16, GL_R16, GL_R16),
    "YUV444P16": (GL_R16, GL_R16, GL_R16),
}
PIXEL_DATA_FORMAT: dict[str, Sequence[IntConstant]] = {
    # defaults to: (GL_RED, GL_RED, GL_RED, GL_RED))
    # (meaning: uploading one channel at a time)
    "NV12": (GL_LUMINANCE, GL_LUMINANCE_ALPHA),  # Y is one channel, UV contains two channels
}
PIXEL_UPLOAD_FORMAT: dict[str, Any] = {
    "r210": GL_UNSIGNED_INT_2_10_10_10_REV,
    "R210": GL_UNSIGNED_INT_10_10_10_2,
    "RGB565": GL_UNSIGNED_SHORT_5_6_5,
    "BGR565": GL_UNSIGNED_SHORT_5_6_5,
    "BGR": GL_UNSIGNED_BYTE,
    "RGB": GL_UNSIGNED_BYTE,
    "BGRA": GL_UNSIGNED_BYTE,
    "BGRX": GL_UNSIGNED_BYTE,
    "RGBA": GL_UNSIGNED_BYTE,
    "RGBX": GL_UNSIGNED_BYTE,
    # planar formats:
    "NV12": (GL_UNSIGNED_BYTE, GL_UNSIGNED_BYTE),
    "YUV420P": (GL_UNSIGNED_BYTE, GL_UNSIGNED_BYTE, GL_UNSIGNED_BYTE),
    "YUV422P": (GL_UNSIGNED_BYTE, GL_UNSIGNED_BYTE, GL_UNSIGNED_BYTE),
    "YUV444P": (GL_UNSIGNED_BYTE, GL_UNSIGNED_BYTE, GL_UNSIGNED_BYTE),
    "YUVA420P": (GL_UNSIGNED_BYTE, GL_UNSIGNED_BYTE, GL_UNSIGNED_BYTE, GL_UNSIGNED_BYTE),
    "YUVA422P": (GL_UNSIGNED_BYTE, GL_UNSIGNED_BYTE, GL_UNSIGNED_BYTE, GL_UNSIGNED_BYTE),
    "YUVA444P": (GL_UNSIGNED_BYTE, GL_UNSIGNED_BYTE, GL_UNSIGNED_BYTE, GL_UNSIGNED_BYTE),
    "GBRP": (GL_UNSIGNED_BYTE, GL_UNSIGNED_BYTE, GL_UNSIGNED_BYTE),
    "GBRP16": (GL_UNSIGNED_SHORT, GL_UNSIGNED_SHORT, GL_UNSIGNED_SHORT),
    "YUV444P10": (GL_UNSIGNED_SHORT, GL_UNSIGNED_SHORT, GL_UNSIGNED_SHORT),
    "YUV420P16": (GL_UNSIGNED_SHORT, GL_UNSIGNED_SHORT, GL_UNSIGNED_SHORT),
    "YUV422P16": (GL_UNSIGNED_SHORT, GL_UNSIGNED_SHORT, GL_UNSIGNED_SHORT),
    "YUV444P16": (GL_UNSIGNED_SHORT, GL_UNSIGNED_SHORT, GL_UNSIGNED_SHORT),
}
CONSTANT_TO_PIXEL_FORMAT: dict[IntConstant, str] = {
    GL_BGR: "BGR",
    GL_RGB: "RGB",
    GL_BGRA: "BGRA",
    GL_RGBA: "RGBA",
}
INTERNAL_FORMAT_TO_STR: dict[IntConstant, str] = {
    GL_RGB10_A2: "RGB10_A2",
    GL_RGBA8: "RGBA8",
    GL_RGB8: "RGB8",
    GL_RGB565: "RGB565",
    GL_RGB5_A1: "RGB5_A1",
    GL_RGBA4: "RGBA4",
    GL_RGBA16: "GL_RGBA16",
}
DATATYPE_TO_STR: dict[IntConstant, str] = {
    GL_UNSIGNED_INT_2_10_10_10_REV: "UNSIGNED_INT_2_10_10_10_REV",
    GL_UNSIGNED_INT_10_10_10_2: "UNSIGNED_INT_10_10_10_2",
    GL_UNSIGNED_BYTE: "UNSIGNED_BYTE",
    GL_UNSIGNED_SHORT: "UNSIGNED_SHORT",
    GL_UNSIGNED_SHORT_5_6_5: "UNSIGNED_SHORT_5_6_5",
}


# Texture number assignment
# The first four are used to update the FBO,
# the FBO is what is painted on screen.
TEX_Y = 0
TEX_U = 1
TEX_V = 2
TEX_A = 3
TEX_RGB = 4
TEX_FBO = 5  # FBO texture (guaranteed up-to-date window contents)
TEX_TMP_FBO = 6
TEX_CURSOR = 7
TEX_FPS = 8
TEX_ALERT = 9
N_TEXTURES = 10


class TemporaryViewport:
    __slots__ = ("viewport", "tmp_viewport")

    def __init__(self, *viewport: int):
        self.viewport = ()
        self.tmp_viewport = viewport

    def __enter__(self):
        self.viewport = glGetIntegerv(GL_VIEWPORT)
        glViewport(*self.tmp_viewport)

    def __exit__(self, *_args):
        glViewport(*self.viewport)

    def __repr__(self):
        return "TemporaryViewport"


def clamp(val: float) -> float:
    return max(0.0, min(1.0, val))


def charclamp(val: int | float) -> int:
    return max(0, min(255, round(val)))


class GLWindowBackingBase(WindowBackingBase):
    """
    The logic is as follows:

    We create an OpenGL framebuffer object, which will be always up-to-date with the latest windows contents.
    This framebuffer object is updated with YUV painting and RGB painting. It is presented on screen by drawing a
    textured quad when requested, that is: after each YUV or RGB painting operation,
    and upon receiving an `expose` event.
    The use of an intermediate framebuffer object is the only way to guarantee that the client keeps
    an always fully up-to-date window image, which is critical because of backbuffer content losses upon buffer swaps
    or offscreen window movement.
    """

    RGB_MODES: Sequence[str] = (
        "YUV420P", "YUV422P", "YUV444P", "NV12",
        "GBRP", "BGRA", "BGRX", "RGBA", "RGBX",
        "RGB", "BGR",
    )
    HAS_ALPHA: bool = GL_ALPHA_SUPPORTED

    def __init__(self, wid: int, window_alpha: bool, pixel_depth: int = 0):
        self.wid: int = wid
        # this is the planar pixel format we are currently updating the fbo with
        # can be: "YUV420P", "YUV422P", "YUV444P", "GBRP" or None when not initialized yet.
        self.planar_pixel_format: str = ""
        self.internal_format = GL_RGBA8
        self.textures = []  # OpenGL texture IDs
        self.shaders: dict[str, GLuint] = {}
        self.programs: dict[str, GLuint] = {}
        self.texture_size: tuple[int, int] = (0, 0)
        self.gl_setup = False
        self.debug_setup = False
        self.border: WindowBorder = WindowBorder(shown=False)
        self.paint_screen = False
        self.offscreen_fbo = None
        self.tmp_fbo = None
        self.vao = None
        self.spinner_vao = None
        self.pending_fbo_paint: list[tuple[int, int, int, int]] = []
        self.last_flush = monotonic()
        self.last_present_fbo_error = ""
        self.alert_uploaded = 0
        self.bit_depth = pixel_depth
        super().__init__(wid, window_alpha and self.HAS_ALPHA)
        self.opengl_init()
        self.paint_context_manager: AbstractContextManager = nullcontext()
        if is_X11():
            # pylint: disable=ungrouped-imports
            from xpra.x11.error import xsync
            self.paint_context_manager = xsync

    def opengl_init(self) -> None:
        self.init_gl_config()
        self.init_backing()
        self.bit_depth = self.get_bit_depth(self.bit_depth)
        self.init_formats()
        self.draw_needs_refresh: bool = DRAW_REFRESH
        # the correct check would be this:
        # `self.repaint_all = self.is_double_buffered() or bw!=ww or bh!=wh`
        # but we're meant to be using double-buffered everywhere,
        # so don't bother and just repaint everything:
        self.repaint_all: bool = True
        assert self._backing is not None
        self._backing.show()

    def get_info(self) -> dict[str, Any]:
        info = super().get_info()
        tif = self.internal_format
        info |= {
            "type": "OpenGL",
            "bit-depth": self.bit_depth,
            "internal-format": INTERNAL_FORMAT_TO_STR.get(tif) or str(tif),
        }
        le = self.last_present_fbo_error
        if le:
            info["last-error"] = le
        return info

    def with_gfx_context(self, function: Callable, *args) -> None:
        # first make the call from the main thread via `idle_add`
        # then run the function from a GL context:
        GLib.idle_add(self.with_gl_context, function, *args)

    def with_gl_context(self, cb: Callable, *args) -> None:
        raise NotImplementedError()

    def init_gl_config(self) -> None:
        raise NotImplementedError()

    def init_backing(self) -> None:
        raise NotImplementedError()

    def gl_context(self) -> Any:
        raise NotImplementedError()

    def do_gl_show(self, rect_count: int) -> None:
        raise NotImplementedError()

    def is_double_buffered(self) -> bool:
        raise NotImplementedError()

    def get_bit_depth(self, pixel_depth: int = 0) -> int:
        return pixel_depth or 24

    def init_formats(self) -> None:
        rgb_modes = list(GLWindowBackingBase.RGB_MODES)
        if self.bit_depth > 32:
            self.internal_format = GL_RGBA16
            rgb_modes.append("r210")
            # self.RGB_MODES.append("GBRP16")
        elif self.bit_depth == 30:
            self.internal_format = GL_RGB10_A2
            rgb_modes.append("r210")
            # self.RGB_MODES.append("GBRP16")
        elif 0 < self.bit_depth <= 16:
            if self._alpha_enabled:
                if envbool("XPRA_GL_RGBA4", True):
                    self.internal_format = GL_RGBA4
                else:
                    self.internal_format = GL_RGB5_A1
                    # too much of a waste to enable?
                    rgb_modes.append("r210")
            else:
                self.internal_format = GL_RGB565
                rgb_modes.append("BGR565")
                rgb_modes.append("RGB565")
        else:
            if self.bit_depth not in (0, 24, 32) and first_time(f"bit-depth-{self.bit_depth}"):
                log.warn(f"Warning: invalid bit depth {self.bit_depth}, using 24")
            # (pixels are always stored in 32bpp - but this makes it clearer when we do/don't support alpha)
            if self._alpha_enabled or ALWAYS_RGBA:
                self.internal_format = GL_RGBA8
            else:
                self.internal_format = GL_RGB8
        self.RGB_MODES = tuple(rgb_modes)
        log("init_formats() internal format=%s, rgb modes=%s",
            INTERNAL_FORMAT_TO_STR.get(self.internal_format),
            self.RGB_MODES)

    def get_encoding_properties(self) -> dict[str, Any]:
        props = super().get_encoding_properties()
        props["encoding.bit-depth"] = self.bit_depth
        return props

    def __repr__(self):
        return f"GLWindowBacking({self.wid:#x}, {self.size})"

    def init(self, ww: int, wh: int, bw: int, bh: int) -> None:
        # re-init gl projection with new dimensions
        # (see gl_init)
        self.render_size = ww, wh
        if self.size != (bw, bh):
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
        sy = (oldh - h) - sy
        dy = (bh - h) - dy
        # re-init our OpenGL context with the new size,
        # but leave offscreen fbo with the old size
        self.gl_init(context, True)
        self.draw_to_tmp()
        if self._alpha_enabled:
            glClearColor(0, 0, 0, 1)
        else:
            glClearColor(1, 1, 1, 0)
        glClear(GL_COLOR_BUFFER_BIT)
        # copy offscreen to new tmp:
        self.copy_fbo(w, h, sx, sy, dx, dy)
        # make tmp the new offscreen:
        self.swap_fbos()
        self.draw_to_offscreen()
        if bw > oldw:
            self.paint_box("padding", oldw, 0, bw - oldw, bh)
        if bh > oldh:
            self.paint_box("padding",0, oldh, bw, bh - oldh)
        # now we don't need the old tmp fbo contents anymore,
        # and we can re-initialize it with the correct size:
        mag_filter = self.get_init_magfilter()
        self.init_fbo(TEX_TMP_FBO, self.tmp_fbo, bw, bh, mag_filter)
        self._backing.queue_draw_area(0, 0, bw, bh)
        if FBO_RESIZE_DELAY >= 0:
            del context

            def redraw(glcontext) -> None:
                if not glcontext:
                    return
                self.pending_fbo_paint = [(0, 0, bw, bh), ]
                self.do_present_fbo(glcontext)

            GLib.timeout_add(FBO_RESIZE_DELAY, self.with_gl_context, redraw)

    def init_textures(self) -> None:
        log("init_textures()")
        assert self.offscreen_fbo is None
        if not bool(glGenFramebuffers):
            raise RuntimeError("current context lacks framebuffer support: no glGenFramebuffers")
        self.textures = glGenTextures(N_TEXTURES)
        self.offscreen_fbo = glGenFramebuffers(1)
        self.tmp_fbo = glGenFramebuffers(1)
        log("%s.init_textures() textures: %s, offscreen fbo: %s, tmp fbo: %s",
            self, self.textures, self.offscreen_fbo, self.tmp_fbo)

    def init_shaders(self) -> None:
        self.vao = glGenVertexArrays(1)
        # Create and assign fragment programs
        from OpenGL.GL import GL_FRAGMENT_SHADER, GL_VERTEX_SHADER
        vertex_shader = self.init_shader("vertex", GL_VERTEX_SHADER)
        from xpra.opengl.shaders import SOURCE
        for name, source in SOURCE.items():
            if name in ("overlay", "blend", "vertex", "fixed-color"):
                continue
            fragment_shader = self.init_shader(name, GL_FRAGMENT_SHADER)
            self.init_program(name, vertex_shader, fragment_shader)
        blend_shader = self.init_shader("blend", GL_FRAGMENT_SHADER)
        overlay_shader = self.init_shader("overlay", GL_FRAGMENT_SHADER)
        fixed_color = self.init_shader("fixed-color", GL_FRAGMENT_SHADER)
        self.init_program("blend", vertex_shader, blend_shader)
        self.init_program("overlay", vertex_shader, overlay_shader)
        self.init_program("fixed-color", vertex_shader, fixed_color)

    def set_vao(self, index=0):
        vertices = [-1, -1, 1, -1, -1, 1, 1, 1]
        # noinspection PyTypeChecker,PyCallingNonCallable
        c_vertices = (c_float * len(vertices))(*vertices)
        glBindVertexArray(self.vao)
        buf = glGenBuffers(1)
        glBindBuffer(GL_ARRAY_BUFFER, buf)
        glBufferData(GL_ARRAY_BUFFER, len(vertices) * 4, c_vertices, GL_STATIC_DRAW)
        glVertexAttribPointer(index, 2, GL_FLOAT, GL_FALSE, 0, c_void_p(0))
        glBindBuffer(GL_ARRAY_BUFFER, 0)
        glEnableVertexAttribArray(index)
        return buf

    def init_program(self, name: str, *shaders: int) -> None:
        from OpenGL.GL import (
            glAttachShader, glDetachShader,
            glCreateProgram, glDeleteProgram, glLinkProgram, glGetProgramInfoLog,
            glGetProgramiv, glValidateProgram,
            GL_FALSE, GL_LINK_STATUS,
        )
        program = glCreateProgram()
        if not program:
            self.fail_shader(name, "glCreateProgram error")
        for shader in shaders:
            glAttachShader(program, shader)
        glLinkProgram(program)
        infolog = glGetProgramInfoLog(program) or "OK"
        status = glGetProgramiv(program, GL_LINK_STATUS)
        if status == GL_FALSE:
            glDeleteProgram(program)
            self.fail_shader(name, infolog)
        log(f"{name} program linked: {infolog!r}")
        self.set_vao()
        status = glValidateProgram(program)
        glBindVertexArray(0)
        infolog = glGetProgramInfoLog(program) or "OK"
        if status == GL_FALSE:
            glDeleteProgram(program)
            self.fail_shader(name, infolog)
        log(f"{name} program validated: {infolog!r}")
        for shader in shaders:
            glDetachShader(program, shader)
        self.programs[name] = program

    def fail_shader(self, name: str, err: str | bytes) -> None:
        err_str = str(err)
        if not isinstance(err, str):
            try:
                err_str = err.decode()
            except UnicodeError:
                pass
        from OpenGL.GL import glDeleteShader
        err_str = err_str.strip("\n\r")
        shader = self.shaders.pop(name, None)
        if shader:
            glDeleteShader(shader)
        log.error(f"Error compiling {name!r} OpenGL shader:")
        for line in err_str.split("\n"):
            if line.strip():
                log.error(" %s", line.strip())
        raise RuntimeError(f"OpenGL failed to compile shader {name!r}: {repr(err_str)}")

    def init_shader(self, name: str, shader_type) -> int:
        # Create and assign fragment programs
        from OpenGL.GL import (
            glCreateShader, glShaderSource, glCompileShader, glGetShaderInfoLog,
            glGetShaderiv,
            GL_COMPILE_STATUS, GL_VERTEX_SHADER, GL_FRAGMENT_SHADER, GL_FALSE,
        )
        assert shader_type in (GL_VERTEX_SHADER, GL_FRAGMENT_SHADER)
        from xpra.opengl.shaders import SOURCE
        progstr = SOURCE[name]
        shader = glCreateShader(shader_type)
        self.shaders[name] = shader
        glShaderSource(shader, progstr)
        glCompileShader(shader)
        infolog = glGetShaderInfoLog(shader) or "OK"
        status = glGetShaderiv(shader, GL_COMPILE_STATUS)
        if status == GL_FALSE:
            log(f"failed shader source {name!r}:")
            for i, line in enumerate(progstr.splitlines()):
                log(f"{i:3}        {line}")
            log("")
            self.fail_shader(name, infolog)
        log(f"{name} shader initialized: {infolog!r}")
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

        if len(self.textures) == 0:
            self.init_textures()

        mag_filter = self.get_init_magfilter()
        # Define empty tmp FBO
        self.init_fbo(TEX_TMP_FBO, self.tmp_fbo, w, h, mag_filter)
        if not skip_fbo:
            # Define empty FBO texture and set rendering to FBO
            self.init_fbo(TEX_FBO, self.offscreen_fbo, w, h, mag_filter)

        # Create and assign fragment programs
        self.init_shaders()

        self.gl_setup = True
        log("gl_init(%s, %s) done", context, skip_fbo)

    def get_init_magfilter(self) -> IntConstant:
        rw, rh = self.render_size
        w, h = self.size
        if rw / w != rw // w or rh / h != rh // h:
            # non integer scaling, use linear magnification filter:
            return GL_LINEAR
        return GL_NEAREST

    def init_fbo(self, texture_index: int, fbo, w: int, h: int, mag_filter) -> None:
        target = GL_TEXTURE_RECTANGLE
        glBindTexture(target, self.textures[texture_index])
        # nvidia needs this even though we don't use mipmaps (repeated through this file):
        glTexParameteri(target, GL_TEXTURE_MAG_FILTER, mag_filter)
        glTexParameteri(target, GL_TEXTURE_MIN_FILTER, GL_NEAREST)
        glTexImage2D(target, 0, self.internal_format, w, h, 0, GL_RGBA, GL_UNSIGNED_BYTE, None)
        glBindFramebuffer(GL_FRAMEBUFFER, fbo)
        glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, target, self.textures[texture_index], 0)
        glDrawBuffer(GL_COLOR_ATTACHMENT0)
        if self._alpha_enabled:
            glClearColor(0, 0, 0, 1)
        else:
            glClearColor(1, 1, 1, 0)
        glClear(GL_COLOR_BUFFER_BIT)

    def close_gl_config(self) -> None:
        """
        Subclasses may free up resources at this point.
        The GTK3 GL drawing area does.
        """

    def close(self) -> None:
        self.with_gl_context(self.close_gl)
        super().close()

    def close_gl(self, context) -> None:
        log("close_gl(%s)", context)
        self.free_cuda_context()
        try:
            from OpenGL.GL import glDeleteProgram, glDeleteShader
            glBindVertexArray(0)
            glUseProgram(0)
            programs = self.programs
            self.programs = {}
            for name, program in programs.items():
                try:
                    log(f"glDeleteProgram({program}) {name!r}")
                    glDeleteProgram(program)
                except GLError as gle:
                    log.error(f"Error deleting {name!r} program")
                    log.error(f" {gle}")
            shaders = self.shaders
            self.shaders = {}
            for name, shader in shaders.items():
                try:
                    log(f"glDeleteShader({shader}) {name!r}")
                    glDeleteShader(shader)
                except GLError as gle:
                    log.error(f"Error deleting {name!r} shader")
                    log.error(f" {gle}")
            vaos = []
            vao = self.vao
            if vao:
                self.vao = None
                vaos.append(vao)
            vao = self.spinner_vao
            if vao:
                self.spinner_vao = None
                vaos.append(vao)
            if vaos:
                glDeleteVertexArrays(1, vaos)
            ofbo = self.offscreen_fbo
            if ofbo is not None:
                self.offscreen_fbo = None
                glDeleteFramebuffers(1, [ofbo])
            textures = self.textures
            if len(textures) > 0:
                self.textures = []
                glDeleteTextures(textures)
        except Exception as e:
            log(f"{self}.close()", exc_info=True)
            log.error("Error closing OpenGL backing, some resources have not been freed")
            log.estr(e)
        b = self._backing
        if b:
            self._backing = None
            b.destroy()
        self.close_gl_config()

    def paint_scroll(self, img_data, options: typedict, callbacks: PaintCallbacks) -> None:
        # newer servers use an option,
        # older ones overload the img_data:
        scroll_data = options.tupleget("scroll", img_data)
        flush = options.intget("flush", 0)
        self.with_gfx_context(self.do_scroll_paints, scroll_data, flush, callbacks)

    def do_scroll_paints(self, context, scrolls, flush: int, callbacks: PaintCallbacks) -> None:
        log("do_scroll_paints%s", (context, scrolls, flush))
        if not context:
            log("%s.do_scroll_paints(..) no context!", self)
            fire_paint_callbacks(callbacks, False, "no opengl context")
            return

        def fail(msg: str) -> None:
            log.error("Error: %s", msg)
            fire_paint_callbacks(callbacks, False, msg)

        bw, bh = self.size
        self.copy_fbo(bw, bh)

        glBindFramebuffer(GL_READ_FRAMEBUFFER, self.tmp_fbo)
        glBindFramebuffer(GL_DRAW_FRAMEBUFFER, self.offscreen_fbo)
        glFlush()

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
            if x + w > bw:
                w = bw - x
            if y + h > bh:
                h = bh - y
            if x + w + xdelta > bw:
                w = bw - x - xdelta
                if w <= 0:
                    continue  # nothing left!
            if y + h + ydelta > bh:
                h = bh - y - ydelta
                if h <= 0:
                    continue  # nothing left!
            if x + xdelta < 0:
                rect = (x, y, w, h)
                fail(f"horizontal scroll {x} by {xdelta} rectangle {rect} overflows the backing buffer size {self.size}")
                continue
            if y + ydelta < 0:
                rect = (x, y, w, h)
                fail(f"vertical scroll {y} by {ydelta} rectangle {rect} overflows the backing buffer size {self.size}")
                continue
            # opengl buffer is upside down, so we must invert Y coordinates: bh-(..)
            glBlitFramebuffer(x, bh - y, x + w, bh - (y + h),
                              x + xdelta, bh - (y + ydelta), x + w + xdelta, bh - (y + h + ydelta),
                              GL_COLOR_BUFFER_BIT, GL_NEAREST)
            self.paint_box("scroll", x + xdelta, y + ydelta, x + w + xdelta, y + h + ydelta)

        glFlush()

        target = GL_TEXTURE_RECTANGLE
        # restore normal paint state:
        glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, target, self.textures[TEX_FBO], 0)
        glBindFramebuffer(GL_READ_FRAMEBUFFER, self.offscreen_fbo)
        glBindFramebuffer(GL_DRAW_FRAMEBUFFER, self.offscreen_fbo)
        glBindFramebuffer(GL_FRAMEBUFFER, self.offscreen_fbo)

        glBindTexture(target, 0)
        self.painted(context, 0, 0, bw, bh, flush)
        fire_paint_callbacks(callbacks, True)

    def copy_fbo(self, w: int, h: int, sx=0, sy=0, dx=0, dy=0) -> None:
        log("copy_fbo%s", (w, h, sx, sy, dx, dy))
        # copy from offscreen to tmp:
        glBindFramebuffer(GL_READ_FRAMEBUFFER, self.offscreen_fbo)
        target = GL_TEXTURE_RECTANGLE
        glBindTexture(target, self.textures[TEX_FBO])
        glFramebufferTexture2D(GL_READ_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, target, self.textures[TEX_FBO], 0)
        glReadBuffer(GL_COLOR_ATTACHMENT0)

        glBindFramebuffer(GL_DRAW_FRAMEBUFFER, self.tmp_fbo)
        glBindTexture(target, self.textures[TEX_TMP_FBO])
        glFramebufferTexture2D(GL_DRAW_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, target, self.textures[TEX_TMP_FBO], 0)
        glDrawBuffer(GL_COLOR_ATTACHMENT0)
        if self._alpha_enabled:
            glClearColor(0, 0, 0, 1)
        else:
            glClearColor(1, 1, 1, 0)
        glClear(GL_COLOR_BUFFER_BIT)

        glBlitFramebuffer(sx, sy, sx + w, sy + h,
                          dx, dy, dx + w, dy + h,
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

    def painted(self, context, x: int, y: int, w: int, h: int, flush=0) -> None:
        if self.draw_needs_refresh:
            # `after_draw_refresh` will end up queuing a draw request,
            # which will call `present_fbo` from `gl_expose_rect`
            return
        self.present_fbo(context, x, y, w, h, flush)

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
            gl_marker("presenting FBO on screen")
            self.managed_present_fbo(context)

    def managed_present_fbo(self, context) -> None:
        if not context:
            raise RuntimeError("missing opengl paint context")
        try:
            with self.paint_context_manager:
                # Change state to target screen instead of our FBO
                glBindFramebuffer(GL_DRAW_FRAMEBUFFER, 0)

                self.do_present_fbo(context)

                # restore pbo viewport
                bw, bh = self.size
                glViewport(0, 0, bw, bh)
                glTexParameteri(GL_TEXTURE_RECTANGLE, GL_TEXTURE_MAG_FILTER, GL_NEAREST)
                glTexParameteri(GL_TEXTURE_RECTANGLE, GL_TEXTURE_MIN_FILTER, GL_NEAREST)
                glBindFramebuffer(GL_DRAW_FRAMEBUFFER, self.offscreen_fbo)
        except Exception as e:
            log.error("Error presenting FBO:")
            log.estr(e)
            log("Error presenting FBO", exc_info=True)
            self.last_present_fbo_error = str(e)

    def do_present_fbo(self, context) -> None:
        # the GL_DRAW_FRAMEBUFFER must already be set when calling this method
        # some backends render to the screen (0), otherws may render elsewhere
        # (ie: the GTK backend renders to its own buffer…)
        bw, bh = self.size
        ww, wh = self.render_size
        xscale = ww / bw * context.get_scale_factor()
        yscale = wh / bh * context.get_scale_factor()
        scaling = xscale != 1 or yscale != 1
        if self.is_double_buffered() or scaling:
            # refresh the whole window:
            rectangles = [(0, 0, bw, bh), ]
        else:
            # paint just the rectangles we have accumulated:
            rectangles = self.pending_fbo_paint
        self.pending_fbo_paint = []
        rect_count = len(rectangles)
        log(f"do_present_fbo({context}) will blit {rectangles}")

        if SAVE_BUFFERS:
            self.save_fbo()

        # viewport for clearing the whole window:
        left, top, right, bottom = self.offsets
        if left or top or right or bottom or xscale or yscale:
            alpha = 0.0 if self._alpha_enabled else 1.0
            glViewport(0, 0, int((left + ww + right) * xscale), int((top + wh + bottom) * yscale))
            glClearColor(0.0, 0.0, 0.0, alpha)
            glClear(GL_COLOR_BUFFER_BIT)

        # from now on, take the offsets and scaling into account:
        viewport = int(left * xscale), int(top * yscale), int(ww * xscale), int(wh * yscale)
        log(f"viewport for render-size={self.render_size} and offsets={self.offsets} with {xscale=} / {yscale=}: {viewport}")
        glViewport(*viewport)

        # Draw FBO texture on screen
        sampling = GL_LINEAR if scaling else GL_NEAREST
        glBindFramebuffer(GL_READ_FRAMEBUFFER, self.offscreen_fbo)
        glFramebufferTexture2D(GL_READ_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_TEXTURE_RECTANGLE, self.textures[TEX_FBO], 0)
        glReadBuffer(GL_COLOR_ATTACHMENT0)

        for x, y, w, h in rectangles:
            glBlitFramebuffer(x, y, w, h,
                              round(x*xscale), round(y*yscale), round((x+w)*xscale), round((y+h)*yscale),
                              GL_COLOR_BUFFER_BIT, sampling)

        if self.pointer_overlay:
            self.draw_pointer(xscale, yscale)

        border = self.border
        if self.alert_state:
            if "shade" in ALERT_MODE:
                self.draw_alert_shade()
            if "dark-shade" in ALERT_MODE:
                self.draw_alert_shade(0.2)
            if "light-shade" in ALERT_MODE:
                self.draw_alert_shade(0.8)
            if "icon" in ALERT_MODE:
                self.draw_alert_icon()
            if "spinner" in ALERT_MODE:
                self.draw_alert_spinner()
            if "small-spinner" in ALERT_MODE:
                self.draw_alert_spinner(40)
            if "big-spinner" in ALERT_MODE:
                self.draw_alert_spinner(90)
            if "border" in ALERT_MODE:
                alpha = clamp(0.1 + (0.9 + sin(monotonic() * 5)) / 2)
                border = WindowBorder(True, 1.0, 0.0, 0.0, alpha, 10)

        if border and border.shown:
            self.draw_border(border)

        if self.is_show_fps():
            self.draw_fps()

        # Show the backbuffer on screen
        glFlush()
        self.gl_show(rect_count)
        gl_frame_terminator()

        log("%s.do_present_fbo() done", self)

    def save_fbo(self) -> None:
        width, height = self.size
        save_fbo(self.wid, self.offscreen_fbo, self.textures[TEX_FBO], width, height, self._alpha_enabled)

    def create_spinner_vao(self, outer_pct=50):
        from xpra.client.gui.spinner import gen_trapezoids
        positions = []
        for inner_left, inner_right, outer_left, outer_right in gen_trapezoids(outer_pct=outer_pct):
            # as two triangles:
            positions += [inner_left] + [inner_right] + [outer_left]
            positions += [outer_left] + [outer_right] + [inner_right]
        # convert to a flat list of 4 coordinates for uploading to an OpenGL buffer:
        verts = []
        for pos in positions:
            verts += [pos[0], pos[1], 0, 1]

        self.spinner_vao = glGenVertexArrays(1)
        glBindVertexArray(self.spinner_vao)

        vbuf = glGenBuffers(1)
        glBindBuffer(GL_ARRAY_BUFFER, vbuf)
        # noinspection PyCallingNonCallable,PyTypeChecker
        glBufferData(GL_ARRAY_BUFFER, (c_float * len(verts))(*verts), GL_STATIC_DRAW)
        glVertexAttribPointer(0, 4, GL_FLOAT, GL_FALSE, 0, None)
        glEnableVertexAttribArray(0)
        glBindBuffer(GL_ARRAY_BUFFER, 0)

    def draw_alert_spinner(self, outer_pct=70) -> None:
        from xpra.client.gui.spinner import NLINES
        if not self.spinner_vao:
            self.create_spinner_vao(outer_pct)

        program = self.programs["fixed-color"]
        glUseProgram(program)
        from OpenGL.GL import (
            glEnable, glDisable,
            GL_BLEND, GL_FUNC_ADD, glBlendEquation, glBlendFunc, GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA,
        )
        glEnable(GL_BLEND)
        glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)
        glBlendEquation(GL_FUNC_ADD)

        glBindVertexArray(self.spinner_vao)
        color = glGetUniformLocation(program, "color")
        now = monotonic()
        for step in range(NLINES):
            v = (1 + sin(step * 2 * pi / NLINES - now * 4)) / 2
            glUniform4f(color, clamp(v), clamp(v), clamp(v + 0.1), clamp(v))
            glDrawArrays(GL_TRIANGLES, step * 6, 6)

        glBindVertexArray(0)
        glDisable(GL_BLEND)

    def upload_alert_texture(self) -> bool:
        if self.alert_uploaded != 0:
            # we have already done it:
            return self.alert_uploaded > 0
        texture = self.textures[TEX_ALERT]
        iw, ih, pixels = WindowBackingBase.get_alert_icon()
        if iw == 0 or ih == 0 or not pixels:
            self.alert_uploaded = -1
            return False
        glActiveTexture(GL_TEXTURE0)
        upload_rgba_texture(int(texture), iw, ih, pixels)
        self.alert_uploaded = 1
        return True

    def draw_alert_shade(self, shade=0.5) -> None:
        rw, rh = self.render_size
        rgba = charclamp(0.2 * 256), charclamp(0.2 * 256), charclamp(0.2 * 256), charclamp(shade * 256)
        pixel = struct.pack(b"!BBBB", *rgba)
        texture = int(self.textures[TEX_RGB])
        upload_rgba_texture(texture, 1, 1, pixel)
        fbo = self.textures[TEX_FBO]
        self.combine_texture("blend", 0, 0, rw, rh, {
            "rgba": texture,
            "dst": fbo,
        }, {"weight": 0.4})

    def draw_alert_icon(self) -> None:
        if not self.upload_alert_texture():
            return
        w, h = 64, 64
        _, rh = self.render_size
        x = 10
        y = rh - h - 10
        alert = self.textures[TEX_ALERT]
        fbo = self.textures[TEX_FBO]
        weight = (1 + sin(monotonic() * 5)) / 4     # sine wave that ranges from 0 to 0.5
        self.combine_texture("blend", x, y, w, h, {
            "rgba": alert,
            "dst": fbo,
        }, {"weight": weight})

    def draw_pointer(self, xscale=1.0, yscale=1.0) -> None:
        px, py, _, _, _, start_time = self.pointer_overlay
        elapsed = monotonic() - start_time
        log("pointer_overlay=%s, elapsed=%.1f, timeout=%s, cursor-data=%s",
            self.pointer_overlay, elapsed, CURSOR_IDLE_TIMEOUT, (self.cursor_data or [])[:7])
        if elapsed >= CURSOR_IDLE_TIMEOUT:
            # timeout - stop showing it:
            self.pointer_overlay = ()
            return
        if not self.cursor_data:
            return
        w = round(self.cursor_data[3] * xscale)
        h = round(self.cursor_data[4] * yscale)
        xhot = self.cursor_data[5]
        yhot = self.cursor_data[6]
        x = round((px - xhot) * xscale)
        y = round((py - yhot) * yscale)
        texture = int(self.textures[TEX_CURSOR])
        self.overlay_texture(texture, x, y, w, h)

    def overlay_texture(self, texture: int, x: int, y: int, w: int, h: int, opacity=0.4) -> None:
        self.combine_texture("overlay", x, y, w, h, {"rgba": texture}, {"opacity": opacity})

    def combine_texture(self, program_name: str, x: int, y: int, w: int, h: int, texture_map: dict, uniforms: dict) -> None:
        log("combine_texture%s", (program_name, x, y, w, h, texture_map))
        # paint this texture

        wh = self.render_size[1]
        target = GL_TEXTURE_RECTANGLE
        # the region we're updating (reversed):
        with TemporaryViewport(x, wh - y - h, w, h):
            program = self.programs[program_name]
            glUseProgram(program)
            index = 0
            for prg_var, texture in texture_map.items():
                glActiveTexture(GL_TEXTURE0 + index)
                glBindTexture(target, texture)
                tex_loc = glGetUniformLocation(program, prg_var)
                # log("glGetUniformLocation(%s, %r)=%i", program_name, prg_var, tex_loc)
                glUniform1i(tex_loc, index)  # 0 -> TEXTURE_0
                index += 1

            for prg_var, value in uniforms.items():
                loc = glGetUniformLocation(program, prg_var)
                # log("glGetUniformLocation(%s, %r)=%i", program_name, prg_var, loc)
                if isinstance(value, int):
                    glUniform1i(loc, value)
                elif isinstance(value, float):
                    glUniform1f(loc, value)
                else:
                    raise TypeError(f"Unsupported type {type(value)}")

            viewport_pos = glGetUniformLocation(program, "viewport_pos")
            glUniform2f(viewport_pos, x, y)

            position = 0
            pos_buffer = self.set_vao(position)

            glDrawArrays(GL_TRIANGLE_STRIP, 0, 4)

            glBindVertexArray(0)
            glUseProgram(0)
            glDeleteBuffers(1, [pos_buffer])

            glBindTexture(target, 0)

    def draw_border(self, border) -> None:
        rgba = charclamp(256 * border.red), charclamp(256 * border.green), charclamp(256 * border.blue), charclamp(256 * border.alpha)
        pixel = struct.pack(b"!BBBB", *rgba)

        texture = int(self.textures[TEX_RGB])
        upload_rgba_texture(texture, 1, 1, pixel)

        rw, rh = self.render_size
        hsize = min(border.size, rw)
        vsize = min(border.size, rh)
        if rw <= hsize or rh <= vsize:
            rects = ((0, 0, rw, rh), )
        else:
            rects = (
                (0, 0, rw, vsize),                              # top
                (rw - hsize, vsize, hsize, rh - vsize * 2),     # right
                (0, rh-vsize, rw, vsize),                       # bottom
                (0, vsize, hsize, rh - vsize * 2),              # left
            )
        fbo = self.textures[TEX_FBO]
        for x, y, w, h in rects:
            self.combine_texture("blend", x, y, w, h, {
                "rgba": texture,
                "dst": fbo,
            }, {"weight": border.alpha})

    def paint_box(self, encoding: str, x: int, y: int, w: int, h: int) -> None:
        # show region being painted if debug paint box is enabled only:
        if self.paint_box_line_width <= 0:
            return
        self.draw_to_offscreen()

        bw, bh = self.size
        color = get_paint_box_color(encoding)
        r, g, b, a = tuple(round(v * 256) for v in color)
        with TemporaryViewport(0, 0, bw, bh):
            self.draw_rectangle(x, y, w, h, self.paint_box_line_width, r, g, b, a, bh)

    def draw_to_tmp(self) -> None:
        target = GL_TEXTURE_RECTANGLE
        glBindFramebuffer(GL_DRAW_FRAMEBUFFER, self.tmp_fbo)
        glBindTexture(target, self.textures[TEX_TMP_FBO])
        glFramebufferTexture2D(GL_DRAW_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, target, self.textures[TEX_TMP_FBO], 0)
        glDrawBuffer(GL_COLOR_ATTACHMENT0)

    def draw_to_offscreen(self) -> None:
        # render to offscreen fbo:
        target = GL_TEXTURE_RECTANGLE
        glBindFramebuffer(GL_DRAW_FRAMEBUFFER, self.offscreen_fbo)
        glBindTexture(target, self.textures[TEX_FBO])
        glFramebufferTexture2D(GL_DRAW_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, target, self.textures[TEX_FBO], 0)
        glDrawBuffer(GL_COLOR_ATTACHMENT0)

    def draw_rectangle(self, x: int, y: int, w: int, h: int, size=1, red=0, green=0, blue=0, alpha=0, bh=0) -> None:
        log("draw_rectangle%s", (x, y, w, h, size, red, green, blue, alpha, bh))
        rgba = charclamp(red), charclamp(green), charclamp(blue), charclamp(alpha)
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
        bh = bh or self.size[1]

        for rx, ry, rw, rh in (
                (x, y, size, h),
                (x + w - size, y, size, h),
                (x + size, y, w - 2 * size, size),
                (x + size, y + h - size, w - 2 * size, size),
        ):
            glBlitFramebuffer(0, 0, 1, 1,
                              rx, bh - ry, rx + rw, bh - (ry + rh),
                              GL_COLOR_BUFFER_BIT, GL_NEAREST)

    def update_fps_buffer(self, width: int, height: int, pixels) -> None:
        # we always call 'record_fps_event' from a gl context,
        # so it is safe to upload the texture:
        texture = int(self.textures[TEX_FPS])
        glActiveTexture(GL_TEXTURE0)
        upload_rgba_texture(texture, width, height, pixels)

    def draw_fps(self) -> None:
        x, y = 2, 5
        width, height = self.fps_buffer_size
        texture = int(self.textures[TEX_FPS])
        self.overlay_texture(texture, x, y, width, height)
        self.cancel_fps_refresh()

        def refresh_screen(context) -> None:
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
        if not cursor_data or len(cursor_data) < 9:
            return False
        cw = int(cursor_data[3])
        ch = int(cursor_data[4])
        pixels = cursor_data[8]
        blen = cw * ch * 4
        if len(pixels) != blen:
            log.error("Error: invalid cursor pixel buffer for %ix%i", cw, ch)
            log.error(" expected %i bytes but got %i (%s)", blen, len(pixels), type(pixels))
            log.error(" %s", repr_ellipsized(hexstr(pixels)))
            return False
        return True

    def get_default_cursor_data(self) -> tuple:
        # use the default cursor
        if self.default_cursor_data:
            return tuple(self.default_cursor_data)
        from xpra.platform.paths import get_icon_dir
        serial = 0
        x = y = 0
        w = h = 32
        xhot = yhot = 16
        pixels = b"d" * w * h * 4
        name = "fake"
        filename = os.path.join(get_icon_dir(), "cross.png")
        log(f"get_default_cursor_data() {filename=}")
        if os.path.exists(filename):
            try:
                from PIL import Image
            except ImportError:
                return ()
            try:
                img = Image.open(filename)
                log(f"get_default_cursor_data() Image({filename=})={img}")
                w, h = img.size
                xhot = w // 2
                yhot = h // 2
                name = "cross"
                if img.mode != "RGBA":
                    img = img.convert("RGBA")
                pixels = img.tobytes("raw", "BGRA")
            except Exception as e:
                log(f"Image.open({filename})", exc_info=True)
                log.warn(f"Warning: failed to load {filename!r}: {e}")
        return "raw", x, y, w, h, xhot, yhot, serial, pixels, name

    def set_cursor_data(self, cursor_data: Sequence) -> None:
        if not cursor_data or cursor_data[0] is None:
            cursor_data = self.get_default_cursor_data()
        self.cursor_data = cursor_data
        if not self.validate_cursor():
            return
        cw = cursor_data[3]
        ch = cursor_data[4]
        pixels = cursor_data[8]

        def upload_cursor(context) -> None:
            if context:
                self.gl_init(context)
                texture = int(self.textures[TEX_CURSOR])
                glActiveTexture(GL_TEXTURE0)
                upload_rgba_texture(texture, cw, ch, pixels)

        self.with_gl_context(upload_cursor)

    def paint_jpeg(self, img_data, x: int, y: int, width: int, height: int,
                   options: typedict, callbacks: PaintCallbacks) -> None:
        self.do_paint_jpeg("jpeg", img_data, x, y, width, height, options, callbacks)

    def paint_jpega(self, img_data, x: int, y: int, width: int, height: int,
                    options: typedict, callbacks: PaintCallbacks) -> None:
        self.do_paint_jpeg("jpega", img_data, x, y, width, height, options, callbacks)

    def do_paint_jpeg(self, encoding, img_data, x: int, y: int, width: int, height: int,
                      options: typedict, callbacks: PaintCallbacks) -> None:
        if width >= 16 and height >= 16:
            if self.nvjpeg_decoder and NVJPEG:
                def paint_nvjpeg(gl_context) -> None:
                    self.paint_nvjpeg(gl_context, encoding, img_data, x, y, width, height, options, callbacks)

                self.with_gfx_context(paint_nvjpeg)
                return
            if self.nvdec_decoder and NVDEC and encoding in self.nvdec_decoder.get_encodings():
                def paint_nvdec(gl_context) -> None:
                    self.paint_nvdec(gl_context, encoding, img_data, x, y, width, height, options, callbacks)

                self.with_gfx_context(paint_nvdec)
                return
        if JPEG_YUV and width >= 2 and height >= 2:
            img = self.jpeg_decoder.decompress_to_yuv(img_data, options)
        else:
            img = self.jpeg_decoder.decompress_to_rgb(img_data, options)
        self.paint_image_wrapper(encoding, img, x, y, width, height, options, callbacks)

    def cuda_buffer_to_pbo(self, gl_context, cuda_buffer, rowstride: int, src_y: int, height: int, stream):
        # must be called with an active cuda context, and from the UI thread
        self.gl_init(gl_context)
        pbo = glGenBuffers(1)
        size = rowstride * height
        glBindBuffer(GL_PIXEL_UNPACK_BUFFER, pbo)
        glBufferData(GL_PIXEL_UNPACK_BUFFER, size, None, GL_STREAM_DRAW)
        glBindBuffer(GL_PIXEL_UNPACK_BUFFER, 0)
        # pylint: disable=import-outside-toplevel
        from pycuda.driver import Memcpy2D  # pylint: disable=no-name-in-module
        from pycuda.gl import RegisteredBuffer, graphics_map_flags  # @UnresolvedImport
        cuda_pbo = RegisteredBuffer(int(pbo), graphics_map_flags.WRITE_DISCARD)
        log("RegisteredBuffer%s=%s", (pbo, graphics_map_flags.WRITE_DISCARD), cuda_pbo)
        mapping = cuda_pbo.map(stream)
        ptr, msize = mapping.device_ptr_and_size()
        if msize < size:
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

    def paint_nvdec(self, context, encoding, img_data, x: int, y: int, width: int, height: int,
                    options: typedict, callbacks: PaintCallbacks) -> None:
        with self.assign_cuda_context(True):
            # we can import pycuda safely here,
            # because `self.assign_cuda_context` will have imported it with the lock:
            from pycuda.driver import Stream, LogicError  # @UnresolvedImport pylint: disable=import-outside-toplevel
            stream = Stream()
            options["stream"] = stream
            img = self.nvdec_decoder.decompress_with_device(encoding, img_data, width, height, options)
            log("paint_nvdec: gl_context=%s, img=%s, downloading buffer to pbo", context, img)
            pixel_format = img.get_pixel_format()
            if pixel_format not in ("NV12",):
                raise ValueError(f"unexpected pixel format {pixel_format}")
            # `pixels` is a cuda buffer with 2 planes: Y then UV
            cuda_buffer = img.get_pixels()
            strides = img.get_rowstride()
            height = img.get_height()
            uvheight = height // 2
            try:
                y_pbo = self.cuda_buffer_to_pbo(context, cuda_buffer, strides[0], 0, height, stream)
                uv_pbo = self.cuda_buffer_to_pbo(context, cuda_buffer, strides[1], roundup(height, 2), uvheight, stream)
            except LogicError as e:
                # disable nvdec from now on:
                self.nvdec_decoder = None
                log("paint_nvdec%s", (context, encoding, img_data, x, y, width, height, options, callbacks))
                raise RuntimeError(f"failed to download nvdec cuda buffer to pbo: {e}")
            finally:
                cuda_buffer.free()
            img.set_pixels((y_pbo, uv_pbo))

        w = img.get_width()
        h = img.get_height()
        options["pbo"] = True
        self.paint_planar(context, "NV12_to_RGB", encoding, img,
                          x, y, w, h, width, height,
                          options, callbacks)

    def paint_nvjpeg(self, gl_context, encoding: str, img_data, x: int, y: int, width: int, height: int,
                     options: typedict, callbacks: PaintCallbacks) -> None:
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

        set_alignment(width, width * len(rgb_format), rgb_format)

        glBindFramebuffer(GL_READ_FRAMEBUFFER, self.tmp_fbo)
        glFramebufferTexture2D(GL_READ_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, target, self.textures[TEX_RGB], 0)
        glReadBuffer(GL_COLOR_ATTACHMENT0)

        glBindFramebuffer(GL_DRAW_FRAMEBUFFER, self.offscreen_fbo)
        glBindTexture(target, self.textures[TEX_FBO])
        glFramebufferTexture2D(GL_DRAW_FRAMEBUFFER, GL_COLOR_ATTACHMENT1, target, self.textures[TEX_FBO], 0)
        glDrawBuffer(GL_COLOR_ATTACHMENT1)

        rh = self.size[1]
        glBlitFramebuffer(0, 0, width, height,
                          x, rh - y, x + width, rh - y - height,
                          GL_COLOR_BUFFER_BIT, GL_NEAREST)

        glBindTexture(target, 0)

        self.paint_box(encoding, x, y, width, height)
        self.painted(gl_context, x, y, width, height, options.intget("flush", 0))
        fire_paint_callbacks(callbacks)
        glDeleteBuffers(1, [pbo])

    def paint_webp(self, img_data, x: int, y: int, width: int, height: int,
                   options: typedict, callbacks: PaintCallbacks) -> None:
        subsampling = options.strget("subsampling", "none")
        has_alpha = options.boolget("has_alpha")
        webp_decoder = self.webp_decoder
        if WEBP_YUV > 0 and webp_decoder and not WEBP_PILLOW and not has_alpha and width >= 2 and height >= 2:
            # webp only uses 'YUV420P' at present, but we can support all of these YUV formats:
            if WEBP_YUV > 1 or subsampling in ("YUV420P", "YUV422P", "YUV444P"):
                img = webp_decoder.decompress_to_yuv(img_data, options)
                self.paint_image_wrapper("webp", img, x, y, width, height, options, callbacks)
                return
        super().paint_webp(img_data, x, y, width, height, options, callbacks)

    def paint_avif(self, img_data, x: int, y: int, width: int, height: int,
                   options: typedict, callbacks: PaintCallbacks) -> None:
        alpha = options.boolget("alpha")
        image = self.avif_decoder.decompress(img_data, options, yuv=not alpha)
        self.paint_image_wrapper("avif", image, x, y, width, height, options, callbacks)

    def do_paint_image_wrapper(self, context, encoding: str, img, x: int, y: int, width: int, height: int,
                               options: typedict, callbacks: PaintCallbacks) -> None:
        # overridden to handle YUV using shaders:
        pixel_format = img.get_pixel_format()
        if pixel_format.startswith("YUV") or pixel_format == "NV12":
            w = img.get_width()
            h = img.get_height()
            shader = f"{pixel_format}_to_RGB"
            if img.get_full_range():
                shader += "_FULL"
            self.paint_planar(context, shader, encoding, img, x, y, w, h, width, height, options, callbacks)
            return
        # this will call do_paint_rgb
        super().do_paint_image_wrapper(context, encoding, img, x, y, width, height, options, callbacks)

    def do_paint_rgb(self, context, encoding: str, rgb_format: str, img_data,
                     x: int, y: int, width: int, height: int, render_width: int, render_height: int, rowstride: int,
                     options: typedict, callbacks: PaintCallbacks) -> None:
        log("%s.do_paint_rgb(%s, %s, %s bytes, x=%d, y=%d, width=%d, height=%d, rowstride=%d, options=%s)",
            self, encoding, rgb_format, len(img_data), x, y, width, height, rowstride, options)
        x, y = self.gravity_adjust(x, y, options)
        if not context:
            log("%s.do_paint_rgb(..) no context!", self)
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

            gl_marker("%s update at (%d,%d) size %dx%d (%s bytes) to %dx%d, using GL %s format=%s / %s to internal=%s",
                      rgb_format, x, y, width, height, len(img_data), render_width, render_height,
                      upload, CONSTANT_TO_PIXEL_FORMAT.get(pformat), DATATYPE_TO_STR.get(ptype),
                      INTERNAL_FORMAT_TO_STR.get(self.internal_format))

            # Upload data as temporary RGB texture
            target = GL_TEXTURE_RECTANGLE
            glBindTexture(target, self.textures[TEX_RGB])
            set_alignment(width, rowstride, rgb_format)
            mag_filter = GL_LINEAR if scaling else GL_NEAREST
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

            rh = self.size[1]
            glBlitFramebuffer(0, 0, width, height,
                              x, rh - y, x + render_width, rh - y - render_height,
                              GL_COLOR_BUFFER_BIT, GL_NEAREST)

            glBindTexture(target, 0)

            self.paint_box(encoding, x, y, render_width, render_height)
            self.painted(context, x, y, render_width, render_height, options.intget("flush", 0))
            fire_paint_callbacks(callbacks)
            return
        except GLError as e:
            message = f"OpenGL {rgb_format} paint failed: {e}"
            log("Error in %s paint of %i bytes, options=%s", rgb_format, len(img_data), options, exc_info=True)
        except Exception as e:
            message = f"OpenGL {rgb_format} paint error: {e}"
            log("Error in %s paint of %i bytes, options=%s", rgb_format, len(img_data), options, exc_info=True)
        fire_paint_callbacks(callbacks, False, message)

    def do_video_paint(self, coding: str, img,
                       x: int, y: int, enc_width: int, enc_height: int, width: int, height: int,
                       options: typedict, callbacks: PaintCallbacks):
        log("do_video_paint%s", (coding, img, x, y, enc_width, enc_height, width, height, options, callbacks))
        if not zerocopy_upload or FORCE_CLONE:
            # copy so the data will be usable (usually a str)
            img.clone_pixel_data()
        pixel_format = img.get_pixel_format()
        if FORCE_VIDEO_PIXEL_FORMAT:
            cd = self.make_csc(enc_width, enc_height, pixel_format,
                               width, height, (FORCE_VIDEO_PIXEL_FORMAT,), options)
            img = cd.convert_image(img)
            pixel_format = img.get_pixel_format()
            log.warn(f"converting to {pixel_format} using {cd}")
            log.warn(f" img={img}")
            log.warn(f" rowstride={img.get_rowstride()}, {pixel_format}")
            cd.clean()
        if pixel_format in ("GBRP10", "YUV444P10"):
            # call superclass to handle csc
            # which will end up calling paint rgb with r210 data
            super().do_video_paint(coding, img, x, y, enc_width, enc_height, width, height, options, callbacks)
            return
        # ignore the bit depth, which is transparent to the shader once we've uploaded the pixel data:
        fmt_name = pixel_format.replace("P16", "P")
        shader = f"{fmt_name}_to_RGB"
        if img.get_full_range():
            shader += "_FULL"
        encoding = options.strget("encoding")
        self.with_gfx_context(self.paint_planar, shader, encoding, img,
                              x, y, enc_width, enc_height, width, height, options, callbacks)

    def paint_planar(self, context, shader: str, encoding: str, img,
                     x: int, y: int, enc_width: int, enc_height: int, width: int, height: int,
                     options: typedict, callbacks: PaintCallbacks) -> None:
        pixel_format = img.get_pixel_format()
        if pixel_format not in PLANAR_FORMATS:
            img.free()
            raise ValueError(f"the GL backing does not handle pixel format {pixel_format!r} yet!")
        if not context:
            img.free()
            log("%s.paint_planar(..) no OpenGL context!", self)
            fire_paint_callbacks(callbacks, False, "failed to get a gl context")
            return
        flush = options.intget("flush", 0)
        x, y = self.gravity_adjust(x, y, options)
        try:
            self.gl_init(context)
            pbo = options.boolget("pbo")
            scaling = enc_width != width or enc_height != height
            try:
                self.update_planar_textures(enc_width, enc_height, img, pixel_format, scaling=scaling, pbo=pbo)
            finally:
                img.free()
            self.render_planar_update(x, y, enc_width, enc_height, width, height, shader)
            self.paint_box(encoding, x, y, width, height)
            self.painted(context, x, y, width, height, flush)
            fire_paint_callbacks(callbacks, True)
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

    def update_planar_textures(self, width: int, height: int, img, pixel_format: str, scaling=False, pbo=False) -> None:
        if len(self.textures) == 0:
            raise RuntimeError("no OpenGL textures")
        upload_formats = PIXEL_UPLOAD_FORMAT[pixel_format]
        internal_formats = PIXEL_INTERNAL_FORMAT.get(pixel_format, (GL_R8, GL_R8, GL_R8, GL_R8))
        data_formats = PIXEL_DATA_FORMAT.get(pixel_format, (GL_RED, GL_RED, GL_RED, GL_RED))
        divs = get_subsampling_divs(pixel_format)
        nplanes = len(divs)
        # textures: usually 3 for "YUV", but only 2 for "NV12", 4 for "YUVA"
        textures = (
            (GL_TEXTURE0, TEX_Y),
            (GL_TEXTURE1, TEX_U),
            (GL_TEXTURE2, TEX_V),
            (GL_TEXTURE3, TEX_A),
        )[:nplanes]
        log("%s.update_planar_textures%s textures=%s", self, (width, height, img, pixel_format, scaling, pbo), textures)
        if self.planar_pixel_format != pixel_format or self.texture_size != (width, height):
            gl_marker("Creating new planar textures, pixel format %r (was %r), texture size %s (was %s)",
                      pixel_format, self.planar_pixel_format, (width, height), self.texture_size)
            gl_marker(" planes=%s, internal_formats=%s, data_formats=%s, upload_formats=%s",
                      csv(get_plane_name(pixel_format, i) for i in range(nplanes)),
                      internal_formats, data_formats, upload_formats)
            self.planar_pixel_format = pixel_format
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
                uformat = upload_formats[index]  # upload format: ie: UNSIGNED_BYTE
                glTexImage2D(target, 0, iformat, width // div_w, height // div_h, 0, dformat, uformat, None)
                # glBindTexture(target, 0)        #redundant: we rebind below:

        gl_marker("updating planar textures: %sx%s %s", width, height, pixel_format)
        rowstrides = img.get_rowstride()
        img_data = img.get_pixels()
        if len(rowstrides) != nplanes or len(img_data) != nplanes:
            raise RuntimeError(f"invalid number of planes for {pixel_format}")
        for texture, index in textures:
            # "YUV420P" -> ("Y", "U", "V")
            # "YUVA420P" -> ("Y", "U", "V", "A")
            # "GBRP16" -> ("GG", "BB", "RR")
            # "NV12" -> ("Y", "UV")
            tex_name = get_plane_name(pixel_format, index)
            dformat = data_formats[index]  # data format: ie: GL_RED
            uformat = upload_formats[index]  # upload format: ie: UNSIGNED_BYTE
            rowstride = rowstrides[index]
            div_w, div_h = divs[index]
            w = width // div_w
            if dformat == GL_LUMINANCE_ALPHA:
                # uploading 2 components
                w //= 2
            elif dformat not in (GL_RED, GL_LUMINANCE):
                raise RuntimeError(f"unexpected data format {dformat} for {pixel_format}")
            h = height // div_h
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
                size = rowstride * h
            else:
                upload, pixel_data = pixels_for_upload(plane)
                size = len(pixel_data)
            glTexParameteri(target, GL_TEXTURE_BASE_LEVEL, 0)
            try:
                glTexParameteri(target, GL_TEXTURE_MAX_LEVEL, 0)
            except GLError:
                pass
            log(f"texture {index}: {tex_name:2} div={div_w},{div_h}, rowstride={rowstride}, {w}x{h}, "
                f"data={size:8} bytes, upload={upload}, format={dformat}, type={uformat}")
            if SHOW_PLANE_RANGES:
                from xpra.codecs.argb.argb import get_plane_range
                log.info("range=%s, hex=%s", get_plane_range(pixel_data, w, rowstride, h), hexstr(pixel_data[:64]))

            glTexSubImage2D(target, 0, 0, 0, w, h, dformat, uformat, pixel_data)
            glBindTexture(target, 0)
            glBindBuffer(GL_PIXEL_UNPACK_BUFFER, 0)
        # glActiveTexture(GL_TEXTURE0)    #redundant, we always call render_planar_update afterwards

    def render_planar_update(self, rx: int, ry: int, rw: int, rh: int, width: int, height: int,
                             shader="YUV420P_to_RGB") -> None:
        log("%s.render_planar_update%s pixel_format=%s",
            self, (rx, ry, rw, rh, width, height, shader), self.planar_pixel_format)
        if self.planar_pixel_format not in (
            "YUV420P", "YUV422P", "YUV444P",
            "YUVA420P", "YUVA422P", "YUVA444P",
            "GBRP", "NV12", "GBRP16",
            "YUV420P16", "YUV422P16", "YUV444P16",
        ):
            # not ready to render yet
            return
        divs = get_subsampling_divs(self.planar_pixel_format)
        textures = (
            (GL_TEXTURE0, TEX_Y),
            (GL_TEXTURE1, TEX_U),
            (GL_TEXTURE2, TEX_V),
            (GL_TEXTURE3, TEX_A),
        )[:len(divs)]
        gl_marker("rendering planar update, format %s", self.planar_pixel_format)

        target = GL_TEXTURE_RECTANGLE
        glBindFramebuffer(GL_DRAW_FRAMEBUFFER, self.offscreen_fbo)
        glBindTexture(target, self.textures[TEX_FBO])
        glFramebufferTexture2D(GL_DRAW_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, target, self.textures[TEX_FBO], 0)
        glDrawBuffer(GL_COLOR_ATTACHMENT0)

        w, h = self.size

        # the region we're updating:

        def clampx(v: int) -> int:
            return min(w, max(0, v))

        def clampy(v: int) -> int:
            return min(h, max(0, v))

        viewport = clampx(rx), clampy(h - ry - height), clampx(width), clampy(height)
        glViewport(*viewport)
        log("viewport: %s for backing size=%s", viewport, self.size)

        program = self.programs.get(shader)
        if not program:
            raise RuntimeError(f"no {shader} found!")
        glUseProgram(program)
        for texture, tex_index in textures:
            glActiveTexture(texture)
            glBindTexture(target, self.textures[tex_index])
            # TEX_Y is 0, so effectively index==tex_index
            index = tex_index-TEX_Y
            plane_name = shader[index:index + 1]  # ie: "YUV420P_to_RGB"  0 -> "Y"
            tex_loc = glGetUniformLocation(program, plane_name)  # ie: "Y" -> 0
            glUniform1i(tex_loc, index)  # tell the shader where to find the texture: 0 -> TEXTURE_0

        # no need to call glGetAttribLocation(program, "position")
        # since we specify the location in the shader:
        position = 0

        viewport_pos = glGetUniformLocation(program, "viewport_pos")
        glUniform2f(viewport_pos, rx, ry)

        scaling = glGetUniformLocation(program, "scaling")
        glUniform2f(scaling, width / rw, height / rh)

        pos_buffer = self.set_vao(position)

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
        flush_elapsed = end - self.last_flush
        self.last_flush = end
        fpslog("gl_show after %3ims took %2ims, %2i updates", flush_elapsed * 1000, (end - start) * 1000, rect_count)

    def gl_expose_rect(self, x: int, y: int, w: int, h: int) -> None:
        if not self.paint_screen:
            return

        def expose(context) -> None:
            if context:
                self.gl_init(context)
                self.present_fbo(context, x, y, w, h)

        self.with_gl_context(expose)
