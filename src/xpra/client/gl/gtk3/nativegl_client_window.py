# This file is part of Xpra.
# Copyright (C) 2017 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.client.gl.gtk3.gl_client_window import GLClientWindowBase
from xpra.client.gl.gtk_base.gl_drawing_area import GLDrawingArea, GLContext

def check_support(force_enable=False, check_colormap=False):
    return GLContext().check_support(force_enable)


class GLClientWindow(GLClientWindowBase):

    def get_backing_class(self):
        return GLDrawingArea
