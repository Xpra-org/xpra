# This file is part of Xpra.
# Copyright (C) 2023 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from typing import Any
from collections.abc import Callable, Sequence

from xpra.common import noop
from xpra.os_util import gi_import
from xpra.util.str_fn import Ellipsizer
from xpra.opengl.backing import GLWindowBackingBase
from xpra.log import Logger

log = Logger("opengl", "paint")

Gtk = gi_import("Gtk")
Gdk = gi_import("Gdk")


def GLArea(alpha: bool) -> Gtk.GLArea:
    glarea = Gtk.GLArea()
    glarea.set_use_es(True)
    glarea.set_auto_render(False)
    glarea.set_has_alpha(alpha)
    glarea.set_has_depth_buffer(False)
    glarea.set_has_stencil_buffer(False)
    glarea.set_required_version(3, 2)
    return glarea


class GLAreaBacking(GLWindowBackingBase):

    def __init__(self, wid: int, window_alpha: bool, pixel_depth: int = 0):
        self.on_realize_cb: list[tuple[Callable, Sequence[Any]]] = []
        super().__init__(wid, window_alpha, pixel_depth)

    def __repr__(self):
        return "GLAreaBacking(%#x, %s)" % (self.wid, self.size)

    def init_gl_config(self) -> None:
        """
        this implementation does not need to initialize a config object
        """

    def close_gl_config(self) -> None:
        """
        there is no config object to close in this implementation
        """

    def is_double_buffered(self) -> bool:
        return True

    def init_backing(self) -> None:
        glarea = GLArea(self._alpha_enabled)
        glarea.connect("realize", self.on_realize)
        glarea.connect("render", self.on_render)
        w, h = self.size
        glarea.set_size_request(w, h)
        add_events = Gdk.EventMask.POINTER_MOTION_MASK | Gdk.EventMask.POINTER_MOTION_HINT_MASK
        glarea.set_events(glarea.get_events() | add_events)
        glarea.show()
        self._backing = glarea

    def on_realize(self, *args) -> None:
        gl_context = self.gl_context()
        gl_context.make_current()
        self.gl_init(gl_context)
        # fire the delayed realized callbacks:
        onrcb = self.on_realize_cb
        log(f"GLAreaBacking.on_realize({args}) callbacks=%s", tuple(Ellipsizer(x) for x in onrcb))
        gl_context.update_geometry = noop
        self.on_realize_cb = []
        for callback, xargs in onrcb:
            with log.trap_error("Error calling realize callback %s", Ellipsizer(callback)):
                callback(gl_context, *xargs)

    def with_gl_context(self, cb: Callable, *args) -> None:
        da = self._backing
        if da and da.get_mapped():
            gl_context = self.gl_context()
            gl_context.make_current()
            cb(gl_context, *args)
        else:
            log("GLAreaBacking.with_gl_context delayed: %s%s", cb, Ellipsizer(args))
            self.on_realize_cb.append((cb, args))

    def get_bit_depth(self, pixel_depth=0) -> int:
        return pixel_depth or 24

    def gl_context(self):
        return self._backing.get_context()

    def do_gl_show(self, rect_count) -> None:
        log(f"do_gl_show({rect_count})")
        self._backing.queue_render()

    def draw_fbo(self, context) -> bool:
        log(f"draw_fbo({context})")
        # we return False which will trigger the "render" signal
        return False

    def on_render(self, glarea, glcontext):
        log(f"on_render({glarea}, {glcontext})")
        if self.textures is None:
            log(" not rendering: no textures!")
            return True
        if self.offscreen_fbo is None:
            log(" not rendering: no offscreen fbo!")
            return True
        glcontext.make_current()

        def get_glarea_scale_factor() -> int:
            backing = self._backing
            scale_factor = 1
            if backing:
                scale_factor = backing.get_scale_factor()
            return scale_factor

        glcontext.get_scale_factor = get_glarea_scale_factor
        self.do_present_fbo(glcontext)
        return True
