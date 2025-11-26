# This file is part of Xpra.
# Copyright (C) 2010 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2011 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from typing import Final
from collections.abc import Iterable, Sequence

from xpra.os_util import gi_import
from xpra.util.gobject import one_arg_signal
from xpra.x11.error import xsync, xswallow
from xpra.x11.common import X11Event
from xpra.x11.bindings.core import constants, get_root_xid
from xpra.x11.bindings.window import X11WindowBindings
from xpra.x11.prop import prop_set, prop_get, prop_del
from xpra.x11.dispatch import add_event_receiver, remove_event_receiver
from xpra.log import Logger

log = Logger("x11", "util")

GObject = gi_import("GObject")


def root_set(prop: str, vtype: list | tuple | str, value) -> None:
    rxid = get_root_xid()
    prop_set(rxid, prop, vtype, value)


def root_get(prop: str, vtype: list | tuple | str):
    rxid = get_root_xid()
    return prop_get(rxid, prop, vtype, ignore_errors=True)


def root_del(prop: str) -> None:
    rxid = get_root_xid()
    prop_del(rxid, prop)


def set_supported() -> None:
    from xpra.x11.common import NET_SUPPORTED
    root_set("_NET_SUPPORTED", ["atom"], NET_SUPPORTED)


def set_workarea(x: int, y: int, width: int, height: int) -> None:
    v = (x, y, width, height)
    log("_NET_WORKAREA=%s", v)
    root_set("_NET_WORKAREA", ["u32"], v)


def get_workareas() -> Sequence[tuple[int, int, int, int]]:
    net_workarea = root_get("_NET_WORKAREA", ["u32"]) or ()
    # workarea comes as a list of 4 CARDINAL dimensions (x,y,w,h), one for each desktop
    nworkareas = len(net_workarea) // 4
    desktop = get_current_desktop()
    log("get_workarea() _NET_WORKAREA=%s (%s), len=%s, desktop=%s",
        net_workarea, type(net_workarea), len(net_workarea), desktop)
    if not net_workarea or (len(net_workarea) % 4) != 0 or desktop < 0 or desktop >= nworkareas:
        return ()
    # slice it:
    workareas = []
    for i in range(nworkareas):
        workareas.append(tuple(net_workarea[i * 4:(i + 1) * 4]))
    return tuple(workareas)


def get_workarea() -> tuple[int, int, int, int]:
    desktop = get_current_desktop()
    workareas = get_workareas()
    if desktop < 0 or desktop >= len(workareas):
        root_w, root_h = get_root_size()
        return 0, 0, root_w, root_h
    return workareas[desktop]


def set_desktop_list(desktops: Sequence[str]) -> None:
    log("set_desktop_list(%s)", desktops)
    root_set("_NET_NUMBER_OF_DESKTOPS", "u32", len(desktops))
    root_set("_NET_DESKTOP_NAMES", ["utf8"], desktops)


def set_current_desktop(index: int) -> None:
    root_set("_NET_CURRENT_DESKTOP", "u32", index)


def get_current_desktop() -> int:
    return root_get("_NET_CURRENT_DESKTOP", "u32") or 0


def set_desktop_geometry(width: int, height: int) -> None:
    v = (width, height)
    log("_NET_DESKTOP_GEOMETRY=%s", v)
    root_set("_NET_DESKTOP_GEOMETRY", ["u32"], v)


def get_desktop_geometry() -> tuple[int, int]:
    desktop_geometry = root_get("_NET_DESKTOP_GEOMETRY", ["u32"])
    if desktop_geometry and len(desktop_geometry) == 2:
        return int(desktop_geometry[0]), int(desktop_geometry[1])
    return get_root_size()


def get_number_of_desktops() -> int:
    return root_get("_NET_NUMBER_OF_DESKTOPS", "u32") or 1


def get_root_size() -> tuple[int, int]:
    with xsync:
        X11Window = X11WindowBindings()
        return X11Window.get_root_size()


def set_desktop_viewport(x=0, y=0) -> None:
    root_set("_NET_DESKTOP_VIEWPORT", ["u32"], (x, y))


def get_desktop_names() -> Sequence[str]:
    names = root_get("_NET_DESKTOP_NAMES", "utf8") or ""
    if not names:
        return ("Main", )
    return names.split("\0")


def _get_icc_xformat(prop="_ICC_PROFILE") -> int:
    fmt = ()
    with xswallow:
        fmt = X11WindowBindings().GetWindowPropertyType(get_root_xid(), prop)
    if not fmt:
        return 0
    xtype, xformat = fmt
    if xtype != "CARDINAL":
        log.warn("Warning: unexpected type for %r: %r", prop, xtype)
        return 0
    if xformat not in (8, 16, 32):
        log.warn("Warning: unexpected format for %r: %r", prop, xformat)
        return 0
    return xformat


def get_icc_profile() -> bytes:
    xformat = _get_icc_xformat("_ICC_PROFILE")
    if not xformat:
        return b""
    data = root_get("_ICC_PROFILE", [f"u{xformat}"]) or ()
    if not data:
        return b""
    try:
        return bytes(data)
    except ValueError as e:
        log.error("Error parsing _ICC_PROFILE: %s", e)
    return b""


def get_icc_version() -> int:
    xformat = _get_icc_xformat("_ICC_PROFILE_IN_X_VERSION")
    if not xformat:
        return 0
    return root_get("_ICC_PROFILE_IN_X_VERSION", f"u{xformat}") or 0


def get_icc_data() -> dict[str, bytes | str | int]:
    profile = get_icc_profile()
    if not profile:
        return {}
    icc: dict[str, bytes | str | int] = {
        "source": "_ICC_PROFILE",
        "data": profile,
    }
    version = get_icc_version()
    if version:
        icc["version"] = version
    return icc


def get_xkb_rules_names() -> Sequence[str]:
    # parses the "_XKB_RULES_NAMES" X11 property
    prop = root_get("_XKB_RULES_NAMES", "latin1")
    log("get_xkb_rules_names() _XKB_RULES_NAMES=%s", prop)
    # ie: 'evdev\x00pc104\x00gb,us\x00,\x00\x00'
    xkb_rules_names: list[str] = []
    if prop:
        xkb_rules_names = prop.split("\0")
    # ie: ['evdev', 'pc104', 'gb,us', ',', '', '']
    log("get_xkb_rules_names()=%s", xkb_rules_names)
    return tuple(xkb_rules_names)


def get_xresources() -> dict[str, str]:
    rm = root_get("RESOURCE_MANAGER", "latin1") or ""
    if not rm:
        return {}
    log(f"RESOURCE_MANAGER={rm!r}")
    # parse the resources into a dict:
    xresources: dict[str, str] = {}
    for line in rm.split("\n"):
        if not line:
            continue
        parts = line.split(":\t", 1)
        if len(parts) != 2:
            log(f"skipped invalid option: {line!r}")
            continue
        xresources[parts[0]] = parts[1]
    return xresources


class XRootPropWatcher(GObject.GObject):
    __gsignals__ = {
        "root-prop-changed": (GObject.SignalFlags.RUN_LAST, GObject.TYPE_NONE, (GObject.TYPE_STRING, )),
        "x11-property-notify-event": one_arg_signal,
    }

    def __init__(self, props: Iterable[str]):
        super().__init__()
        self._props = props
        with xsync:
            rxid = get_root_xid()
            X11Window = X11WindowBindings()
            mask = X11Window.getEventMask(rxid)
            self._saved_event_mask = mask
            PropertyChangeMask: Final[int] = constants["PropertyChangeMask"]
            X11Window.setEventMask(rxid, mask | PropertyChangeMask)
        add_event_receiver(rxid, self)

    def cleanup(self) -> None:
        # this must be called from the UI thread!
        with xsync:
            rxid = get_root_xid()
            X11Window = X11WindowBindings()
            X11Window.setEventMask(rxid, self._saved_event_mask)
        remove_event_receiver(rxid, self)

    def __repr__(self):  # pylint: disable=arguments-differ
        return "XRootPropWatcher"

    def do_x11_property_notify_event(self, event: X11Event) -> None:
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
