# This file is part of Xpra.
# Copyright (C) 2023 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from typing import Any

from xpra.os_util import gi_import
from xpra.client.gtk3.opengl.client_window import GLClientWindowBase
from xpra.log import Logger

log = Logger("opengl", "paint")

Gtk = gi_import("Gtk")
GObject = gi_import("GObject")


class GLClientWindow(GLClientWindowBase):

    def get_backing_class(self) -> type:
        from xpra.client.gtk3.opengl.glarea_backing import GLAreaBacking
        return GLAreaBacking

    def repaint(self, x: int, y: int, w: int, h: int) -> None:
        widget = self.drawing_area
        log(f"repaint%s {widget=}", (x, y, w, h))
        if widget:
            widget.queue_render()


GObject.type_register(GLClientWindow)


def check_support(force_enable=False) -> dict[str, Any]:
    window = Gtk.Window(type=Gtk.WindowType.TOPLEVEL)
    window.set_default_size(400, 400)
    window.resize(400, 400)
    window.set_decorated(False)
    window.realize()
    from xpra.client.gtk3.opengl.glarea_backing import GLArea
    glarea = GLArea(True)
    from xpra.gtk.window import set_visual
    set_visual(glarea, True)
    window.add(glarea)
    glarea.realize()
    gl_context = glarea.get_context()
    gl_context.make_current()
    try:
        from xpra.opengl.check import check_PyOpenGL_support
        return check_PyOpenGL_support(force_enable)
    finally:
        window.destroy()
