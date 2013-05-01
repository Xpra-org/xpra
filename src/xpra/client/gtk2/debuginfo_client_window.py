# This file is part of Xpra.
# Copyright (C) 2011 Serviware (Arthur Huillet, <ahuillet@serviware.com>)
# Copyright (C) 2010-2013 Antoine Martin <antoine@devloop.org.uk>
# Copyright (C) 2008, 2010 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import datetime
import gtk
import gobject
from xpra.client.gtk2.topbar_client_window import TopBarClientWindow
from xpra.deque import maxdeque

from xpra.log import Logger
log = Logger()


"""
Shows the latest logging message for this window in the top bar.
"""
class DebugInfoClientWindow(TopBarClientWindow):

    def __init__(self, *args):
        log.info("DebugInfoClientWindow.__init__(%s)", args)
        TopBarClientWindow.__init__(self, *args)
        if self._has_custom_decorations:
            self.log_buffer = maxdeque(100)
            self.capture_log = True
            self.debug = lambda *x : self._add_log_event("debug", *x)
            self.info = lambda *x : self._add_log_event("info", *x)
            self.warn = lambda *x : self._add_log_event("warn", *x)
            self.error = lambda *x : self._add_log_event("error", *x)

    def _add_log_event(self, level, msg, *args, **kwargs):
        if not self.capture_log:
            return
        s = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S") + " " + str(msg) % (args)
        if kwargs:
            s += " - %s" % str(kwargs)
        log.info("add_log_event: %s", s)
        self.log_buffer.append(s)
        self.debug_label.set_text(s)
        h = self._offset[3]
        w, _ = self._size
        self.queue_draw(0, 0, w, h)

    def add_top_bar_widgets(self, hbox):
        self.debug_label = gtk.Label("DEBUG AREA")
        hbox.add(self.debug_label)

    def do_expose_event(self, event):
        self.capture_log = False
        TopBarClientWindow.do_expose_event(self, event)
        self.capture_log = True

gobject.type_register(DebugInfoClientWindow)
