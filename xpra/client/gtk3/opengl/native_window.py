# This file is part of Xpra.
# Copyright (C) 2017 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from typing import Any

from xpra.os_util import gi_import
from xpra.client.gtk3.opengl.client_window import GLClientWindowBase
from xpra.platform.gl_context import GLContext

GObject = gi_import("GObject")


def check_support(force_enable=False) -> dict[str, Any]:
    import warnings  # pylint: disable=import-outside-toplevel
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", message=".*g_object_get_qdata:")
        warnings.filterwarnings("ignore", message=".*g_object_set_qdata_full:")
        warnings.filterwarnings("ignore", message=".*g_object_unref:")
        return GLContext().check_support(force_enable)  # pylint: disable=not-callable


class GLClientWindow(GLClientWindowBase):

    def get_backing_class(self):
        # delay the import so we can trap warnings in gl.check
        # and use the numpy import context:
        from xpra.client.gtk3.opengl.drawing_area import GLDrawingArea
        return GLDrawingArea


GObject.type_register(GLClientWindow)
