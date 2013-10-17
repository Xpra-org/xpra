# This file is part of Xpra.
# Copyright (C) 2010 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2011-2013 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import gtk
import gobject
from xpra.gtk_common.gobject_util import n_arg_signal
from xpra.x11.gtk_x11.gdk_bindings import add_event_receiver, remove_event_receiver    #@UnresolvedImport
from xpra.x11.gtk_x11.gdk_bindings import init_x11_filter   #@UnresolvedImport

from xpra.log import Logger
log = Logger()


class XRootPropWatcher(gobject.GObject):
    __gsignals__ = {
        "root-prop-changed": (gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE, (gobject.TYPE_STRING, )),
        "xpra-property-notify-event": n_arg_signal(1),
        }

    def __init__(self, props):
        gobject.GObject.__init__(self)
        self._props = props
        self._root = gtk.gdk.get_default_root_window()
        self._saved_event_mask = self._root.get_events()
        self._root.set_events(self._saved_event_mask | gtk.gdk.PROPERTY_CHANGE_MASK)
        init_x11_filter()
        add_event_receiver(self._root, self)

    def cleanup(self):
        remove_event_receiver(self._root, self)
        self._root.set_events(self._saved_event_mask)

    def do_xpra_property_notify_event(self, event):
        log("XRootPropWatcher.do_xpra_property_notify_event(%s)", event)
        if event.atom in self._props:
            self.do_notify(event.atom)

    def do_notify(self, prop):
        log("XRootPropWatcher.do_notify(%s)", prop)
        self.emit("root-prop-changed", prop)

    def notify_all(self):
        for prop in self._props:
            self.do_notify(prop)


gobject.type_register(XRootPropWatcher)
