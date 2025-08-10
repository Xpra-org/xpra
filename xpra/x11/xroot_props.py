# This file is part of Xpra.
# Copyright (C) 2010 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2011 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from typing import Final
from collections.abc import Iterable, Sequence

from xpra.os_util import gi_import
from xpra.util.gobject import one_arg_signal
from xpra.x11.error import xsync
from xpra.x11.bindings.core import get_root_xid
from xpra.x11.bindings.window import constants, X11WindowBindings
from xpra.x11.prop import prop_set, prop_get, prop_del
from xpra.x11.dispatch import add_event_receiver, remove_event_receiver
from xpra.log import Logger

log = Logger("x11", "util")
screenlog = Logger("x11", "screen")

GObject = gi_import("GObject")

PropertyChangeMask: Final[int] = constants["PropertyChangeMask"]

rxid: Final[int] = get_root_xid()


def root_set(prop: str, vtype: list | tuple | str, value) -> None:
    prop_set(rxid, prop, vtype, value)


def root_get(prop: str, vtype: list | tuple | str, *args, **kwargs):
    return prop_get(rxid, prop, vtype, *args, **kwargs)


def root_del(prop: str) -> None:
    prop_del(rxid, prop)


def set_supported() -> None:
    from xpra.x11.common import NET_SUPPORTED
    root_set("_NET_SUPPORTED", ["atom"], NET_SUPPORTED)


def set_workarea(x: int, y: int, width: int, height: int) -> None:
    v = (x, y, width, height)
    screenlog("_NET_WORKAREA=%s", v)
    root_set("_NET_WORKAREA", ["u32"], v)


def set_desktop_list(desktops: Sequence[str]) -> None:
    log("set_desktop_list(%s)", desktops)
    root_set("_NET_NUMBER_OF_DESKTOPS", "u32", len(desktops))
    root_set("_NET_DESKTOP_NAMES", ["utf8"], desktops)


def set_current_desktop(index: int) -> None:
    root_set("_NET_CURRENT_DESKTOP", "u32", index)


def set_desktop_geometry(width: int, height: int) -> None:
    v = (width, height)
    screenlog("_NET_DESKTOP_GEOMETRY=%s", v)
    root_set("_NET_DESKTOP_GEOMETRY", ["u32"], v)


def get_desktop_geometry() -> tuple[int, int]:
    desktop_geometry = root_get("_NET_DESKTOP_GEOMETRY", ["u32"], True, False)
    if desktop_geometry and len(desktop_geometry) == 2:
        return int(desktop_geometry[0]), int(desktop_geometry[1])
    with xsync:
        X11Window = X11WindowBindings()
        root_w, root_h = X11Window.getGeometry(rxid)[2:4]
        return root_w, root_h


def set_desktop_viewport(x=0, y=0) -> None:
    root_set("_NET_DESKTOP_VIEWPORT", ["u32"], (x, y))


class XRootPropWatcher(GObject.GObject):
    __gsignals__ = {
        "root-prop-changed": (GObject.SignalFlags.RUN_LAST, GObject.TYPE_NONE, (GObject.TYPE_STRING, )),
        "x11-property-notify-event": one_arg_signal,
    }

    def __init__(self, props: Iterable[str]):
        super().__init__()
        self._props = props
        with xsync:
            X11Window = X11WindowBindings()
            mask = X11Window.getEventMask(rxid)
            self._saved_event_mask = mask
            X11Window.setEventMask(rxid, mask | PropertyChangeMask)
        add_event_receiver(rxid, self)

    def cleanup(self) -> None:
        # this must be called from the UI thread!
        with xsync:
            X11Window = X11WindowBindings()
            X11Window.setEventMask(rxid, self._saved_event_mask)
        remove_event_receiver(rxid, self)

    def __repr__(self):  # pylint: disable=arguments-differ
        return "XRootPropWatcher"

    def do_x11_property_notify_event(self, event) -> None:
        log("XRootPropWatcher.do_x11_property_notify_event(%s)", event)
        if event.atom in self._props:
            self.do_notify(str(event.atom))

    def do_notify(self, prop: str) -> None:
        log("XRootPropWatcher.do_notify(%s)", prop)
        self.emit("root-prop-changed", prop)

    def notify_all(self) -> None:
        for prop in self._props:
            self.do_notify(prop)


GObject.type_register(XRootPropWatcher)
