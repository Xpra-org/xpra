# This file is part of Xpra.
# Copyright (C) 2010 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2011-2019 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from gi.repository import GObject, Gdk

from xpra.gtk_common.gobject_util import one_arg_signal, SIGNAL_RUN_LAST
from xpra.x11.gtk_x11.gdk_bindings import (
    add_event_receiver, remove_event_receiver,
    )
from xpra.log import Logger

log = Logger("x11", "util")


class XRootPropWatcher(GObject.GObject):
    __gsignals__ = {
        "root-prop-changed": (SIGNAL_RUN_LAST, GObject.TYPE_NONE, (GObject.TYPE_STRING, )),
        "xpra-property-notify-event": one_arg_signal,
        }

    def __init__(self, props, root_window):
        GObject.GObject.__init__(self)
        self._props = props
        self._root = root_window
        self._saved_event_mask = self._root.get_events()
        self._root.set_events(self._saved_event_mask | Gdk.EventMask.PROPERTY_CHANGE_MASK)
        add_event_receiver(self._root, self)

    def cleanup(self):
        #this must be called from the UI thread!
        remove_event_receiver(self._root, self)
        self._root.set_events(self._saved_event_mask)


    def __repr__(self):
        return "XRootPropWatcher"


    def do_xpra_property_notify_event(self, event):
        log("XRootPropWatcher.do_xpra_property_notify_event(%s)", event)
        if event.atom in self._props:
            self.do_notify(str(event.atom))

    def do_notify(self, prop):
        log("XRootPropWatcher.do_notify(%s)", prop)
        self.emit("root-prop-changed", prop)

    def notify_all(self):
        for prop in self._props:
            self.do_notify(prop)


GObject.type_register(XRootPropWatcher)
