# This file is part of Xpra.
# Copyright (C) 2017 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.gtk_common import gi_init
from gi.repository import GObject               #@UnresolvedImport @UnusedImport

from xpra.client.gl.gtk3.gl_client_window import GLClientWindowBase
from xpra.client.gl.gtk_base.gl_drawing_area import GLDrawingArea, GLContext

def check_support(force_enable=False, check_colormap=False):
    import warnings
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", message=".*g_object_get_qdata:")
        warnings.filterwarnings("ignore", message=".*g_object_set_qdata_full:")
        warnings.filterwarnings("ignore", message=".*g_object_unref:")
        return GLContext().check_support(force_enable)  #pylint: disable=not-callable

assert gi_init


class GLClientWindow(GLClientWindowBase):
    __gsignals__ = GLClientWindowBase.__common_gsignals__

    def get_backing_class(self):
        return GLDrawingArea

GObject.type_register(GLClientWindow)
