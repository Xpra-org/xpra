# This file is part of Xpra.
# Copyright (C) 2023 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from typing import Any
from collections.abc import Callable
from gi.repository import Gtk, Gdk, GObject

from xpra.common import noop
from xpra.util.str_fn import ellipsizer
from xpra.client.gl.gtk3.client_window import GLClientWindowBase
from xpra.client.gl.backing import GLWindowBackingBase
from xpra.log import Logger

log = Logger("opengl", "paint")


class GLAreaBacking(GLWindowBackingBase):

    def __init__(self, wid : int, window_alpha : bool, pixel_depth : int=0):
        self.on_realize_cb : list[tuple[Callable,tuple[Any,...]]] = []
        super().__init__(wid, window_alpha, pixel_depth)

    def __repr__(self):
        return "GLAreaBacking(%#x, %s, %s)" % (self.wid, self.size, self.pixel_format)

    def init_gl_config(self) -> None:
        pass

    def is_double_buffered(self) -> bool:
        return True

    def init_backing(self) -> None:
        da = Gtk.GLArea()
        da.set_use_es(True)
        da.set_auto_render(True)
        da.set_has_alpha(self._alpha_enabled)
        da.set_has_depth_buffer(False)
        da.set_has_stencil_buffer(False)
        da.set_required_version(3, 2)
        da.connect("realize", self.on_realize)
        da.connect("render", self.on_render)
        da.set_size_request(*self.size)
        da.set_events(da.get_events() | Gdk.EventMask.POINTER_MOTION_MASK | Gdk.EventMask.POINTER_MOTION_HINT_MASK)
        da.show()
        self._backing = da

    def on_realize(self, *args) -> None:
        gl_context = self.gl_context()
        gl_context.make_current()
        self.gl_init(gl_context)
        # fire the delayed realized callbacks:
        onrcb = self.on_realize_cb
        log(f"GLAreaBacking.on_realize({args}) callbacks=%s", tuple(ellipsizer(x) for x in onrcb))
        gl_context.update_geometry = noop
        self.on_realize_cb = []
        for x, xargs in onrcb:
            with log.trap_error("Error calling realize callback %s", ellipsizer(x)):
                x(gl_context, *xargs)

    def with_gl_context(self, cb:Callable, *args):
        da = self._backing
        if da and da.get_mapped():
            gl_context = self.gl_context()
            gl_context.make_current()
            cb(gl_context, *args)
        else:
            log("GLAreaBacking.with_gl_context delayed: %s%s", cb, ellipsizer(args))
            self.on_realize_cb.append((cb, args))

    def get_bit_depth(self, pixel_depth=0) -> int:
        return pixel_depth or 24

    def gl_context(self):
        return self._backing.get_context()

    def do_gl_show(self, rect_count) -> None:
        log.warn(f"do_gl_show({rect_count})")
        self._backing.queue_render()

    def close_gl_config(self) -> None:
        pass

    def draw_fbo(self, context) -> bool:
        log.warn(f"draw_fbo({context})")
        #window = self._backing.get_window()
        #from xpra.client.gl.backing import TEX_FBO
        #from OpenGL.GL import GL_TEXTURE
        #w, h = self.render_size
        #self.textures[TEX_FBO]
        #Gdk.cairo_draw_from_gl(context, window, self.textures[TEX_FBO], GL_TEXTURE, 1, 0, 0, w, h)
        return False

    def on_render(self, glarea, glcontext):
        log(f"render({glarea}, {glcontext}) {self.textures=}, {self.offscreen_fbo=}")
        if self.textures is None or self.offscreen_fbo is None:
            return True
        glcontext.make_current()
        w, h = self.render_size
        from xpra.client.gl.backing import TEX_FBO
        if False:
            def noscale():
                return 1
            glcontext.get_scale_factor = noscale
            self.managed_present_fbo(glcontext)
        else:
            # TODO: handle widget scaling!
            #https://discourse.gnome.org/t/solved-framebuffer-issue-render-to-texture-with-gtk3-glarea-vs-glfw-identical-opengl-program-works-in-glfw-but-not-gtk3s-glarea/3597
            #current = glGetIntegerv(GL_FRAMEBUFFER_BINDING)
            from OpenGL.GL import GL_COLOR_BUFFER_BIT, GL_NEAREST, glReadBuffer, glClear, glClearColor
            from OpenGL.GL.ARB.texture_rectangle import GL_TEXTURE_RECTANGLE_ARB
            from OpenGL.GL.ARB.framebuffer_object import glBindFramebuffer, GL_READ_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, glBlitFramebuffer, glFramebufferTexture2D
            glClearColor(0, 0, 0, 0)
            glClear(GL_COLOR_BUFFER_BIT)
            target = GL_TEXTURE_RECTANGLE_ARB
            glBindFramebuffer(GL_READ_FRAMEBUFFER, self.offscreen_fbo)
            glFramebufferTexture2D(GL_READ_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, target, self.textures[TEX_FBO], 0)
            glReadBuffer(GL_COLOR_ATTACHMENT0)
            glBlitFramebuffer(0, 0, w, h,
                              0, 0, w, h,
                              GL_COLOR_BUFFER_BIT, GL_NEAREST)
        return True


class GLClientWindow(GLClientWindowBase):

    def get_backing_class(self):
        return GLAreaBacking

    def repaint(self, x:int, y:int, w:int, h:int) -> None:
        widget = self.drawing_area
        log(f"repaint%s {widget=}", (x, y, w, h))
        if widget:
            widget.queue_render()

GObject.type_register(GLClientWindow)


def check_support(force_enable=False):
    if True:
        from xpra.client.gl.window import test_gl_client_window
        return test_gl_client_window(GLClientWindow)
    window = Gtk.Window(title="opengl-check")
    window.set_default_size(400, 400)
    gl_area = GLAreaBacking()
    gl_area.set_has_depth_buffer(False)
    gl_area.set_has_stencil_buffer(False)
    window.add(gl_area)
    gl_area.realize()
    return {}
