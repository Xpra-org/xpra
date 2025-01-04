# This file is part of Xpra.
# Copyright (C) 2017 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from typing import Any
from collections.abc import Sequence
from contextlib import AbstractContextManager
from ctypes import c_int, c_void_p, byref, cast, POINTER

from xpra.os_util import gi_import
from xpra.util.env import envbool, envfloat, numpy_import_context
from xpra.opengl.check import check_PyOpenGL_support
from xpra.x11.bindings.display_source import get_display_ptr
from xpra.gtk.error import xsync
from xpra.gtk.window import set_visual
from xpra.log import Logger

with numpy_import_context("OpenGL: glx context", True):
    from OpenGL import GLX
    from OpenGL.GL import GL_VENDOR, GL_RENDERER, glGetString
    from OpenGL.raw.GLX._types import struct__XDisplay, struct___GLXcontextRec

log = Logger("opengl")

ARB_CONTEXT = envbool("XPRA_OPENGL_ARB_CONTEXT", True)
CORE_PROFILE = envbool("XPRA_OPENGL_CORE_PROFILE", True)
DOUBLE_BUFFERED = envbool("XPRA_OPENGL_DOUBLE_BUFFERED", True)
SCALE_FACTOR = envfloat("XPRA_OPENGL_SCALE_FACTOR", 1)
if SCALE_FACTOR <= 0 or SCALE_FACTOR > 10:
    raise ValueError(f"invalid scale factor {SCALE_FACTOR}")

GLX_ATTRIBUTES: dict[Any, str] = {
    GLX.GLX_ACCUM_RED_SIZE: "accum-red-size",
    GLX.GLX_ACCUM_GREEN_SIZE: "accum-green-size",
    GLX.GLX_ACCUM_BLUE_SIZE: "accum-blue-size",
    GLX.GLX_ACCUM_ALPHA_SIZE: "accum-alpha-size",
    GLX.GLX_RED_SIZE: "red-size",
    GLX.GLX_GREEN_SIZE: "green-size",
    GLX.GLX_BLUE_SIZE: "blue-size",
    GLX.GLX_ALPHA_SIZE: "alpha-size",
    GLX.GLX_DEPTH_SIZE: "depth-size",
    GLX.GLX_STENCIL_SIZE: "stencil-size",
    GLX.GLX_BUFFER_SIZE: "buffer-size",
    GLX.GLX_AUX_BUFFERS: "aux-buffers",
    GLX.GLX_DOUBLEBUFFER: "double-buffered",
    GLX.GLX_LEVEL: "level",
    GLX.GLX_STEREO: "stereo",
    GLX.GLX_RGBA: "rgba",
}


def c_attrs(props: dict):
    attrs = []
    for k, v in props.items():
        if v is None:
            attrs += [k]
        else:
            attrs += [k, v]
    attrs += [0, 0]
    # noinspection PyTypeChecker,PyCallingNonCallable
    return (c_int * len(attrs))(*attrs)


XDISPLAY = int    # POINTER(struct__XDisplay)


def get_xdisplay() -> XDISPLAY:
    ptr = get_display_ptr()
    if not ptr:
        raise RuntimeError("no X11 display registered")
    return cast(ptr, POINTER(struct__XDisplay))


def get_extensions(xdisplay: int) -> Sequence[str]:
    bext = GLX.glXQueryExtensionsString(xdisplay, 0)
    if not bext:
        return ()
    str_ext = bext.decode("latin1")
    return tuple(x for x in str_ext.strip().split(" ") if x)


def get_fbconfig_attributes(xdisplay: int, fbconfig) -> dict[str, int]:
    fb_attrs: dict[str, int] = {}
    for name, attr in {
        "fbconfig-id": GLX.GLX_FBCONFIG_ID,
        "level": GLX.GLX_LEVEL,
        "double-buffer": GLX.GLX_DOUBLEBUFFER,
        "stereo": GLX.GLX_STEREO,
        "aux-buffers": GLX.GLX_AUX_BUFFERS,
        "red-size": GLX.GLX_RED_SIZE,
        "green-size": GLX.GLX_GREEN_SIZE,
        "blue-size": GLX.GLX_BLUE_SIZE,
        "alpha-size": GLX.GLX_ALPHA_SIZE,
        "depth-size": GLX.GLX_DEPTH_SIZE,
        "stencil-size": GLX.GLX_STENCIL_SIZE,
        "accum-red-size": GLX.GLX_ACCUM_RED_SIZE,
        "accum-green-size": GLX.GLX_ACCUM_GREEN_SIZE,
        "accum-blue-size": GLX.GLX_ACCUM_BLUE_SIZE,
        "accum-alpha-size": GLX.GLX_ACCUM_ALPHA_SIZE,
        "render-type": GLX.GLX_RENDER_TYPE,
        "drawable-type": GLX.GLX_DRAWABLE_TYPE,
        "renderable": GLX.GLX_X_RENDERABLE,
        "visual-id": GLX.GLX_VISUAL_ID,
        "visual-type": GLX.GLX_X_VISUAL_TYPE,
        "config-caveat": GLX.GLX_CONFIG_CAVEAT,
        "transparent-type": GLX.GLX_TRANSPARENT_TYPE,
        "transparent-index-value": GLX.GLX_TRANSPARENT_INDEX_VALUE,
        "transparent-red-value": GLX.GLX_TRANSPARENT_RED_VALUE,
        "transparent-green-value": GLX.GLX_TRANSPARENT_GREEN_VALUE,
        "transparent-blue-value": GLX.GLX_TRANSPARENT_BLUE_VALUE,
        "transparent-alpha-value": GLX.GLX_TRANSPARENT_ALPHA_VALUE,
        "max-pbuffer-width": GLX.GLX_MAX_PBUFFER_WIDTH,
        "max-pbuffer-height": GLX.GLX_MAX_PBUFFER_HEIGHT,
        "max-pbuffer-pixels": GLX.GLX_MAX_PBUFFER_PIXELS,
    }.items():
        value = c_int()
        if not GLX.glXGetFBConfigAttrib(xdisplay, fbconfig, attr, byref(value)):
            fb_attrs[name] = value.value
    return fb_attrs


class GLXWindowContext(AbstractContextManager):

    def __init__(self, glx_context, xid: int):
        self.context = glx_context
        self.xid = xid
        self.xdisplay: XDISPLAY = get_xdisplay()
        self.valid: bool = False

    def __enter__(self):
        log("glXMakeCurrent: xid=%#x, context=%s", self.xid, self.context)
        with xsync:
            if not GLX.glXMakeCurrent(self.xdisplay, self.xid, self.context):
                raise RuntimeError("glXMakeCurrent failed")
        self.valid = True
        return self

    def __exit__(self, *_args):
        self.valid = False
        if self.context:
            context_type = type(self.context)
            null_context = cast(0, context_type)
            log("glXMakeCurrent: NULL for xid=%#x", self.xid)
            if not GLX.glXMakeCurrent(self.xdisplay, 0, null_context):
                log.error("Error: glXMakeCurrent NULL failed")

    def update_geometry(self) -> None:
        """ not needed on X11 """

    def swap_buffers(self) -> None:
        assert self.valid, "GLX window context is no longer valid"
        GLX.glXSwapBuffers(self.xdisplay, self.xid)

    def get_scale_factor(self) -> float:
        return SCALE_FACTOR

    def __repr__(self):
        return "GLXWindowContext(%#x)" % self.xid


class GLXContext:

    def __init__(self, alpha=False):
        self.props: dict[str, Any] = {}
        self.xdisplay: int = 0
        self.context = None
        self.bit_depth: int = 0
        self.xdisplay = get_xdisplay()

        # query version
        major = c_int()
        minor = c_int()
        if not GLX.glXQueryVersion(self.xdisplay, byref(major), byref(minor)):
            raise RuntimeError("failed to query GLX version")
        log("found GLX version %i.%i", major.value, minor.value)
        self.props["GLX"] = (major.value, minor.value)

        # find a framebuffer config we can use:
        bpc = 8
        pyattrs = {
            GLX.GLX_X_RENDERABLE: True,
            GLX.GLX_DRAWABLE_TYPE: GLX.GLX_WINDOW_BIT,
            GLX.GLX_RENDER_TYPE: GLX.GLX_RGBA_BIT,
            GLX.GLX_X_VISUAL_TYPE: GLX.GLX_TRUE_COLOR,
            GLX.GLX_RED_SIZE: bpc,
            GLX.GLX_GREEN_SIZE: bpc,
            GLX.GLX_BLUE_SIZE: bpc,
            GLX.GLX_DEPTH_SIZE: 24,
            GLX.GLX_STENCIL_SIZE: 8,
        }
        if alpha:
            pyattrs[GLX.GLX_ALPHA_SIZE] = int(alpha) * bpc
        if DOUBLE_BUFFERED:
            pyattrs[GLX.GLX_DOUBLEBUFFER] = True
        attrs = c_attrs(pyattrs)
        fbcount = c_int()
        fbc = GLX.glXChooseFBConfig(self.xdisplay, 0, attrs, byref(fbcount))
        log(f"glXChooseFBConfig(..)={fbc} {fbcount=}")
        if fbcount.value <= 0:
            raise RuntimeError(f"no frame buffer configurations found matching {pyattrs}")
        for i in range(fbcount.value):
            fb_attrs = get_fbconfig_attributes(self.xdisplay, fbc[i])
            log(f"[{i:2}] {fb_attrs}")
        fbconfig = fbc[0]
        log(f"using {fbconfig=}")
        # the X11 visual for this framebuffer config:
        xvinfo = GLX.glXGetVisualFromFBConfig(self.xdisplay, fbconfig)

        # query extensions:
        extensions = get_extensions(self.xdisplay)
        log(f"{extensions=}")

        def getconfig(attr: int) -> int:
            value = c_int()
            r = GLX.glXGetConfig(self.xdisplay, xvinfo, attr, byref(value))
            if r:
                raise RuntimeError(f"glXGetConfig({attr}) returned {r}")
            return value.value

        if not getconfig(GLX.GLX_USE_GL):
            raise RuntimeError("OpenGL is not supported by this visual!")

        self.bit_depth = sum(getconfig(x) for x in (
            GLX.GLX_RED_SIZE,
            GLX.GLX_GREEN_SIZE,
            GLX.GLX_BLUE_SIZE,
            GLX.GLX_ALPHA_SIZE,
        ))
        self.props["depth"] = self.bit_depth
        # hide those because we don't use them
        # and because they're misleading: 'has-alpha' may be False
        # even when we have RGBA support (and therefore very likely to have alpha..)
        # self.props["has-depth-buffer"] = getconfig(GLX.GLX_DEPTH_SIZE)>0
        # self.props["has-stencil-buffer"] = getconfig(GLX.GLX_STENCIL_SIZE)>0
        # self.props["has-alpha"] = getconfig(GLX.GLX_ALPHA_SIZE)>0
        for attrib, name in GLX_ATTRIBUTES.items():
            v = getconfig(attrib)
            if name in ("stereo", "double-buffered", "rgba"):
                v = bool(v)
            self.props[name] = v
        # attribute names matching gtkgl:
        display_mode = []
        if getconfig(GLX.GLX_RGBA):
            # this particular context may not have alpha channel support...
            # but if we have RGBA then it's almost guaranteed that we can do ALPHA
            display_mode.append("ALPHA")
        if getconfig(GLX.GLX_DOUBLEBUFFER):
            display_mode.append("DOUBLE")
        else:  # pragma: no cover
            display_mode.append("SINGLE")
        self.props["display_mode"] = display_mode
        if ARB_CONTEXT and "GLX_ARB_create_context" in extensions:
            from OpenGL.raw.GLX.ARB.create_context import (
                # glXCreateContextAttribsARB,
                GLX_CONTEXT_FLAGS_ARB,
                GLX_CONTEXT_MAJOR_VERSION_ARB, GLX_CONTEXT_MINOR_VERSION_ARB,
            )
            from OpenGL.raw.GLX.ARB.create_context_profile import (
                GLX_CONTEXT_PROFILE_MASK_ARB,
                GLX_CONTEXT_CORE_PROFILE_BIT_ARB, GLX_CONTEXT_COMPATIBILITY_PROFILE_BIT_ARB,
            )
            if CORE_PROFILE:
                profile_mask = GLX_CONTEXT_CORE_PROFILE_BIT_ARB
            else:
                profile_mask = GLX_CONTEXT_COMPATIBILITY_PROFILE_BIT_ARB
            context_attrs = c_attrs({
                GLX_CONTEXT_MAJOR_VERSION_ARB: 3,
                GLX_CONTEXT_MINOR_VERSION_ARB: 2,
                GLX_CONTEXT_PROFILE_MASK_ARB: profile_mask,
                GLX_CONTEXT_FLAGS_ARB: 0,
            })
            glXCreateContextAttribsARB = GLX.glXGetProcAddress("glXCreateContextAttribsARB")
            log(f"{glXCreateContextAttribsARB=} {context_attrs=}")
            glXCreateContextAttribsARB.argtypes = [POINTER(struct__XDisplay), c_void_p, c_int, c_int, POINTER(c_int)]
            glXCreateContextAttribsARB.restype = POINTER(struct___GLXcontextRec)
            self.context = glXCreateContextAttribsARB(self.xdisplay, fbconfig, 0, True, context_attrs)
        else:
            self.context = GLX.glXCreateNewContext(self.xdisplay, fbconfig, GLX.GLX_RGBA_TYPE, None, True)
        log(f"gl context={self.context}")
        self.props["direct"] = bool(GLX.glXIsDirect(self.xdisplay, self.context))

        def getstr(k) -> str:
            try:
                return glGetString(k)
            except Exception as e:  # pragma: no cover
                self.props["safe"] = False
                result = getattr(e, "result", None)
                if result and isinstance(result, str):
                    return result
                raise

        self.props["vendor"] = getstr(GL_VENDOR)
        self.props["renderer"] = getstr(GL_RENDERER)
        log("GLXContext(%s) context=%s, props=%s", alpha, self.context, self.props)

    def check_support(self, force_enable=False) -> dict[str, Any]:
        i = self.props
        if not self.xdisplay:
            return {
                "success": False,
                "safe": False,
                "enabled": False,
                "message": "cannot access X11 display",
            }
        Gtk = gi_import("Gtk")
        tmp = Gtk.Window(type=Gtk.WindowType.TOPLEVEL)
        tmp.resize(1, 1)
        tmp.set_decorated(False)
        tmp.realize()
        da = Gtk.DrawingArea()
        tmp.add(da)
        set_visual(da, True)
        win = tmp.get_window()
        log("check_support(%s) using temporary window=%s", force_enable, tmp)
        with self.get_paint_context(win):
            i.update(check_PyOpenGL_support(force_enable))
        tmp.destroy()
        return i

    def get_bit_depth(self) -> int:
        return self.bit_depth

    def is_double_buffered(self) -> bool:
        return DOUBLE_BUFFERED

    def get_paint_context(self, gdk_window) -> GLXWindowContext:
        if not self.context:
            raise RuntimeError("no glx context")
        if not gdk_window:
            raise RuntimeError("cannot get a paint context without a window")
        return GLXWindowContext(self.context, gdk_window.get_xid())

    def destroy(self) -> None:
        c = self.context
        if c:
            self.context = None
            GLX.glXDestroyContext(self.xdisplay, c)

    def __repr__(self):
        return f"GLXContext({self.props})"


GLContext = GLXContext


def check_support() -> dict[str, Any]:
    ptr = get_display_ptr()
    if not ptr:
        from xpra.x11.gtk.display_source import init_gdk_display_source
        init_gdk_display_source()

    return GLContext().check_support()
