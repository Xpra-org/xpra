# This file is part of Xpra.
# Copyright (C) 2017 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys
from gi.repository import GObject               #@UnresolvedImport @UnusedImport

from xpra.client.gl.gtk3.gl_client_window import GLClientWindowBase
from xpra.platform.gl_context import GLContext
if not GLContext:
    raise ImportError("no OpenGL context implementation for %s" % sys.platform)

def check_support(force_enable=False):
    import warnings  #pylint: disable=import-outside-toplevel
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", message=".*g_object_get_qdata:")
        warnings.filterwarnings("ignore", message=".*g_object_set_qdata_full:")
        warnings.filterwarnings("ignore", message=".*g_object_unref:")
        return GLContext().check_support(force_enable)  #pylint: disable=not-callable


class GLClientWindow(GLClientWindowBase):
    __gsignals__ = GLClientWindowBase.__common_gsignals__

    def get_backing_class(self):
        from xpra.client.gl.gtk3.gl_drawing_area import GLDrawingArea
        return GLDrawingArea


GObject.type_register(GLClientWindow)
