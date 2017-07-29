# This file is part of Xpra.
# Copyright (C) 2010 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2011-2017 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from gtk import gdk
import gobject
from xpra.gtk_common.gobject_util import n_arg_signal, SIGNAL_RUN_LAST
from xpra.x11.gtk2.gdk_bindings import (add_event_receiver, remove_event_receiver,  #@UnresolvedImport
                                        cleanup_all_event_receivers)                #@UnresolvedImport
from xpra.gtk_common.error import xsync

from xpra.log import Logger
log = Logger("x11", "util")


class XRootPropWatcher(gobject.GObject):
    __gsignals__ = {
        "root-prop-changed": (SIGNAL_RUN_LAST, gobject.TYPE_NONE, (gobject.TYPE_STRING, )),
        "xpra-property-notify-event": n_arg_signal(1),
        }

    def __init__(self, props, root_window):
        gobject.GObject.__init__(self)
        self._props = props
        self._root = root_window
        self._saved_event_mask = self._root.get_events()
        self._root.set_events(self._saved_event_mask | gdk.PROPERTY_CHANGE_MASK)
        add_event_receiver(self._root, self)

    def cleanup(self):
        #this must be called from the UI thread!
        remove_event_receiver(self._root, self)
        self._root.set_events(self._saved_event_mask)
        #try a few times:
        #errors happen because windows are being destroyed
        #(even more so when we cleanup)
        #and we don't really care too much about this
        for l in (log, log, log, log, log.warn):
            try:
                with xsync:
                    cleanup_all_event_receivers()
                    #all went well, we're done
                    return
            except Exception as e:
                l("failed to remove event receivers: %s", e)

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
