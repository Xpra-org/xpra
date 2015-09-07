# This file is part of Xpra.
# Copyright (C) 2011 Serviware (Arthur Huillet, <ahuillet@serviware.com>)
# Copyright (C) 2010-2015 Antoine Martin <antoine@devloop.org.uk>
# Copyright (C) 2008, 2010 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import gobject
import gtk.gdk
from xpra.client.gtk2.client_window import ClientWindow


"""
Adds a red border around the window contents
"""
class BorderClientWindow(ClientWindow):

    def setup_window(self, *args):
        self.border = None
        ClientWindow.setup_window(self, *args)

    def magic_key(self, *args):
        self.border_shown = (not self.border_shown)
        self.queue_draw(0, 0, *self._size)

    def do_expose_event(self, event):
        ClientWindow.do_expose_event(self, event)
        if self.border is None or not self.border.shown:
            return
        #now paint our border import gtk.gdk
        s = self.border.size
        ww, wh = self.window.get_size()
        borders = []
        #window is wide enough, add borders on the side:
        borders.append((0, 0, s, wh))           #left
        borders.append((ww-s, 0, s, wh))        #right
        #window is tall enough, add borders on top and bottom:
        borders.append((0, 0, ww, s))           #top
        borders.append((0, wh-s, ww, s))        #bottom
        for x, y, w, h in borders:
            if w<=0 or h<=0:
                continue
            r = gtk.gdk.Rectangle(x, y, w, h)
            rect = event.area.intersect(r)
            if rect.width==0 or rect.height==0:
                continue
            context = self.window.cairo_create()
            context.rectangle(rect)
            context.clip()
            context.set_source_rgba(self.border.red, self.border.green, self.border.blue, self.border.alpha)
            context.fill()
            context.paint()

gobject.type_register(BorderClientWindow)
