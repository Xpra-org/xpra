# This file is part of Xpra.
# Copyright (C) 2017 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.log import Logger
log = Logger("opengl")

from xpra.util import envbool
from xpra.client.gl.gl_check import check_PyOpenGL_support
from xpra.x11.bindings.display_source import get_display_ptr        #@UnresolvedImport
from xpra.gtk_common.gobject_compat import get_xid
from xpra.gtk_common.gtk_util import display_get_default, get_default_root_window
from ctypes import c_int, byref
from OpenGL import GLX


DOUBLE_BUFFERED = envbool("XPRA_OPENGL_DOUBLE_BUFFERED", True)


def c_attrs(props):
    attrs = []
    for k,v in props.items():
        attrs += [k, v]
    attrs += [0, 0]
    return (c_int * len(attrs))(*attrs)

def get_xdisplay():
    ptr = get_display_ptr()
    from OpenGL.raw.GLX._types import struct__XDisplay
    from ctypes import cast, POINTER
    return cast(ptr, POINTER(struct__XDisplay))
    

class GLXWindowContext(object):

    def __init__(self, glx_context, xid):
        self.context = glx_context
        self.xid = xid
        self.xdisplay = get_xdisplay()
        self.valid = False

    def __enter__(self):
        if not GLX.glXMakeCurrent(self.xdisplay, self.xid, self.context):
            raise Exception("glXMakeCurrent failed")
        self.valid = True

    def __exit__(self, *_args):
        self.valid = False

    def swap_buffers(self):
        assert self.valid
        GLX.glXSwapBuffers(self.xdisplay, self.xid)

    def __repr__(self):
        return "gtk3.GLXWindowContext(%#x)" % self.xid


class GLXContext(object):

    def __init__(self):
        display = display_get_default()
        screen = display.get_default_screen()
        attrs = c_attrs({
            GLX.GLX_RGBA            : True,
            GLX.GLX_RED_SIZE        : 8,
            GLX.GLX_GREEN_SIZE      : 8,
            GLX.GLX_BLUE_SIZE       : 8,
            GLX.GLX_DOUBLEBUFFER    : int(DOUBLE_BUFFERED),
            })
        self.props = {}
        self.xdisplay = get_xdisplay()
        xvinfo = GLX.glXChooseVisual(self.xdisplay, screen.get_number(), attrs)
        def getconfig(attrib):
            value = c_int()
            r = GLX.glXGetConfig(self.xdisplay, xvinfo, attrib, byref(value))
            assert r==0, "glXGetConfig returned %i" % r
            return value.value
        assert getconfig(GLX.GLX_USE_GL), "OpenGL is not supported by this visual!"
        major = c_int()
        minor = c_int()
        assert GLX.glXQueryVersion(self.xdisplay, byref(major), byref(minor))
        log("found GLX version %i.%i", major.value, minor.value)
        self.props["GLX"] = (major, minor)
        self.bit_depth = getconfig(GLX.GLX_RED_SIZE) + getconfig(GLX.GLX_GREEN_SIZE) + getconfig(GLX.GLX_BLUE_SIZE)
        self.props["depth"] = self.bit_depth
        self.props["has-depth-buffer"] = getconfig(GLX.GLX_DEPTH_SIZE)>0
        self.props["has-stencil-buffer"] = getconfig(GLX.GLX_STENCIL_SIZE)>0
        self.props["has-alpha"] = getconfig(GLX.GLX_ALPHA_SIZE)>0
        for attrib,name in {
            GLX.GLX_ACCUM_RED_SIZE      : "accum-red-size",
            GLX.GLX_ACCUM_GREEN_SIZE    : "accum-green-size",
            GLX.GLX_ACCUM_BLUE_SIZE     : "accum-blue-size",
            GLX.GLX_ACCUM_ALPHA_SIZE    : "accum-alpha-size",
            GLX.GLX_RED_SIZE            : "red-size",
            GLX.GLX_GREEN_SIZE          : "green-size",
            GLX.GLX_BLUE_SIZE           : "blue-size",
            GLX.GLX_ALPHA_SIZE          : "alpha-size",
            GLX.GLX_DEPTH_SIZE          : "depth-size",
            GLX.GLX_STENCIL_SIZE        : "stencil-size",
            GLX.GLX_BUFFER_SIZE         : "buffer-size",
            GLX.GLX_AUX_BUFFERS         : "aux-buffers",
            GLX.GLX_DOUBLEBUFFER        : "double-buffered",
            GLX.GLX_LEVEL               : "level",
            GLX.GLX_STEREO              : "stereo",
            GLX.GLX_RGBA                : "rgba",
            }.items():
            v = getconfig(attrib)
            if name in ("stereo", "double-buffered", "rgba"):
                v = bool(v)
            self.props[name] = v
        self.context = GLX.glXCreateContext(self.xdisplay, xvinfo, None, True)
        self.props["direct"] = bool(GLX.glXIsDirect(self.xdisplay, self.context))
        log("GLXContext() context=%s, props=%s", self.context, self.props)

    def check_support(self, force_enable=False):
        i = self.props
        root = get_default_root_window()
        with self.get_paint_context(root):
            i.update(check_PyOpenGL_support(force_enable))
        return i

    def get_bit_depth(self):
        return self.bit_depth

    def is_double_buffered(self):
        return DOUBLE_BUFFERED

    def get_paint_context(self, gdk_window):
        assert self.context and gdk_window
        return GLXWindowContext(self.context, get_xid(gdk_window))

    def destroy(self):
        c = self.context
        if c:
            self.context = None
            GLX.glXDestroyContext(self.xdisplay, c)

    def __repr__(self):
        return "GLXContext"

GLContext = GLXContext
