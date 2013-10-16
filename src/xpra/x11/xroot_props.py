# This file is part of Xpra.
# Copyright (C) 2010 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2011-2013 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import gtk
import gobject
from xpra.gtk_common.gobject_util import n_arg_signal
from xpra.x11.gtk_x11.gdk_bindings import add_event_receiver, remove_event_receiver    #@UnresolvedImport
from xpra.x11.gtk_x11.prop import prop_get

from xpra.log import Logger
log = Logger()


class XRootPropWatcher(gobject.GObject):
    __gsignals__ = {
        "root-prop-changed": (gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE, (gobject.TYPE_STRING, gobject.TYPE_STRING,)),
        "xpra-property-notify-event": n_arg_signal(1),
        }

    def __init__(self, props):
        gobject.GObject.__init__(self)
        self._props = props
        self._root = gtk.gdk.get_default_root_window()
        add_event_receiver(self._root, self)

    def cleanup(self):
        remove_event_receiver(self._root, self)

    def do_xpra_property_notify_event(self, event):
        log("XRootPropWatcher.do_xpra_property_notify_event(%s) props=%s", event, self._props)
        if event.atom in self._props:
            self._notify(event.atom)

    def _notify(self, prop):
        v = prop_get(self._root, prop, "latin1", ignore_errors=True)
        self.emit("root-prop-changed", prop, str(v))

    def notify_all(self):
        for prop in self._props:
            self._notify(prop)


gobject.type_register(XRootPropWatcher)
