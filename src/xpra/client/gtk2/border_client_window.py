# This file is part of Xpra.
# Copyright (C) 2011 Serviware (Arthur Huillet, <ahuillet@serviware.com>)
# Copyright (C) 2010-2013 Antoine Martin <antoine@devloop.org.uk>
# Copyright (C) 2008, 2010 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import gobject
from xpra.client.gtk2.client_window import ClientWindow


"""
Adds a red border around the window contents
"""
class BorderClientWindow(ClientWindow):

    def init_window(self, metadata):
        ClientWindow.init_window(self, metadata)
        if not self._override_redirect:
            self._offset = 6, 6, 6, 6

    def paint_offset(self, event, context):
        oL, oT, oR, oB = self._offset
        w, h = self._size
        #draw red frame:
        context.set_source_rgb(1.0, 0.0, 0.0)
        #left size (top to bottom):
        context.rectangle(0, 0, oL, oT+h+oB)
        context.fill()
        #right side (top to bottom):
        context.rectangle(oL+w, 0, oR, oT+h+oB)
        context.fill()
        #top side:
        context.rectangle(oL, 0, w, oT)
        context.fill()
        #bottom side:
        context.rectangle(oL, h+oT, w, oB)
        context.fill()

gobject.type_register(BorderClientWindow)
