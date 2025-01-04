# This file is part of Xpra.
# Copyright (C) 2010 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2011 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from typing import Final
from collections.abc import Iterable

from xpra.os_util import gi_import
from xpra.gtk.gobject import one_arg_signal
from xpra.gtk.error import xsync
from xpra.x11.bindings.window import constants, X11WindowBindings
from xpra.x11.gtk.bindings import add_event_receiver, remove_event_receiver
from xpra.log import Logger

log = Logger("x11", "util")

GObject = gi_import("GObject")
Gdk = gi_import("Gdk")

PropertyChangeMask: Final[int] = constants["PropertyChangeMask"]

X11Window = X11WindowBindings()


class XRootPropWatcher(GObject.GObject):
    __gsignals__ = {
        "root-prop-changed": (GObject.SignalFlags.RUN_LAST, GObject.TYPE_NONE, (GObject.TYPE_STRING, )),
        "x11-property-notify-event": one_arg_signal,
    }

    def __init__(self, props: Iterable[str]):
        super().__init__()
        self._props = props
        with xsync:
            root_xid = X11Window.get_root_xid()
            mask = X11Window.getEventMask(root_xid)
            self._saved_event_mask = mask
            X11Window.setEventMask(root_xid, mask | PropertyChangeMask)
        add_event_receiver(root_xid, self)

    def cleanup(self) -> None:
        # this must be called from the UI thread!
        with xsync:
            root_xid = X11Window.get_root_xid()
            X11Window.setEventMask(root_xid, self._saved_event_mask)
        remove_event_receiver(root_xid, self)

    def __repr__(self):  # pylint: disable=arguments-differ
        return "XRootPropWatcher"

    def do_x11_property_notify_event(self, event) -> None:
        log("XRootPropWatcher.do_x11_property_notify_event(%s)", event)
        if event.atom in self._props:
            self.do_notify(str(event.atom))

    def do_notify(self, prop: str):
        log("XRootPropWatcher.do_notify(%s)", prop)
        self.emit("root-prop-changed", prop)

    def notify_all(self) -> None:
        for prop in self._props:
            self.do_notify(prop)


GObject.type_register(XRootPropWatcher)
