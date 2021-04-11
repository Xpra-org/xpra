# This file is part of Xpra.
# Copyright (C) 2017 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import gobject  #@UnresolvedImport

from xpra.client.gl.gtk2.gl_client_window import GLClientWindowBase
from xpra.client.gl.gtk_base.gl_drawing_area import GLDrawingArea, GLContext

def check_support(force_enable=False, check_colormap=False):    #pylint: disable=unused-argument
    return GLContext().check_support(force_enable)  #pylint: disable=not-callable


class GLClientWindow(GLClientWindowBase):

    __gsignals__ = GLClientWindowBase.__common_gsignals__

    def get_backing_class(self):
        return GLDrawingArea


gobject.type_register(GLClientWindow)
