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
from xpra.x11.prop import array_get, array_set, prop_set, prop_get, prop_del
from xpra.x11.dispatch import add_event_receiver, remove_event_receiver
from xpra.log import Logger

log = Logger("x11", "util")

GObject = gi_import("GObject")

# GTK exports one `_GTK_WORKAREAS_D#` property per desktop,
# each one containing the workarea of every monitor:
GTK_WORKAREAS_PREFIX: Final[str] = "_GTK_WORKAREAS_D"
# matches the limit used when exporting the desktop list:
MAX_DESKTOPS: Final[int] = 20


def root_set(prop: str, vtype: str, value) -> None:
    rxid = get_root_xid()
    prop_set(rxid, prop, vtype, value)


def root_array_set(prop: str, vtype: str, value: Sequence) -> None:
    rxid = get_root_xid()
    array_set(rxid, prop, vtype, value)


def root_get(prop: str, vtype: str):
    rxid = get_root_xid()
    return prop_get(rxid, prop, vtype, ignore_errors=True)


def root_array_get(prop: str, vtype: str):
    rxid = get_root_xid()
    return array_get(rxid, prop, vtype, ignore_errors=True)


def root_del(prop: str) -> None:
    rxid = get_root_xid()
    prop_del(rxid, prop)


def set_supported() -> None:
    from xpra.x11.common import NET_SUPPORTED
    root_array_set("_NET_SUPPORTED", "atom", NET_SUPPORTED)


def split_rects(values: Sequence[int]) -> tuple[tuple[int, int, int, int], ...]:
    # both `_NET_WORKAREA` and `_GTK_WORKAREAS_D#` are flat lists of `(x, y, w, h)` CARDINALs
    if not values or (len(values) % 4) != 0:
        return ()
    return tuple(tuple(values[i:i + 4]) for i in range(0, len(values), 4))  # type: ignore[misc]


def set_workarea(x: int, y: int, width: int, height: int) -> None:
    v = (x, y, width, height)
    log("_NET_WORKAREA=%s", v)
    root_array_set("_NET_WORKAREA", "u32", v)


def set_workareas(workareas: Sequence[tuple[int, int, int, int]], desktops: int = 0) -> None:
    """ export the per-monitor workareas as `_GTK_WORKAREAS_D#`, one property per desktop.
        (we use the same workareas on every desktop)
        GTK will only look at this property if `_GTK_WORKAREAS` is listed in `_NET_SUPPORTED`.
    """
    ndesktops = desktops or get_number_of_desktops()
    flat: list[int] = []
    for workarea in workareas:
        flat += list(workarea)
    log("_GTK_WORKAREAS=%s on %i desktops", workareas, ndesktops)
    for i in range(ndesktops):
        prop = f"{GTK_WORKAREAS_PREFIX}{i}"
        if flat:
            root_array_set(prop, "u32", flat)
        else:
            root_del(prop)
    # remove any properties left over from a larger desktop count:
    for i in range(ndesktops, MAX_DESKTOPS):
        prop = f"{GTK_WORKAREAS_PREFIX}{i}"
        if root_array_get(prop, "u32") is None:
            break
        root_del(prop)


def get_net_workareas() -> Sequence[tuple[int, int, int, int]]:
    # `_NET_WORKAREA` contains one workarea for each desktop:
    net_workarea = root_array_get("_NET_WORKAREA", "u32") or ()
    workareas = split_rects(net_workarea)
    log("get_net_workareas() _NET_WORKAREA=%s (%s)=%s", net_workarea, type(net_workarea), workareas)
    return workareas


def get_gtk_workareas() -> Sequence[tuple[int, int, int, int]]:
    # `_GTK_WORKAREAS_D#` contains one workarea for each monitor, for the desktop `#`:
    desktop = get_current_desktop()
    prop = f"{GTK_WORKAREAS_PREFIX}{max(0, desktop)}"
    values = root_array_get(prop, "u32") or ()
    workareas = split_rects(values)
    log("get_gtk_workareas() %s=%s (%s)=%s", prop, values, type(values), workareas)
    return workareas


def get_workareas() -> Sequence[tuple[int, int, int, int]]:
    # one workarea per monitor - only `_GTK_WORKAREAS_D#` can provide that,
    # `_NET_WORKAREA` is per desktop and must not be mistaken for a per-monitor list:
    return get_gtk_workareas()


def get_workarea() -> tuple[int, int, int, int]:
    # a single workarea for the whole screen:
    gtk_workareas = get_gtk_workareas()
    if len(gtk_workareas) == 1:
        # unambiguous: a single monitor, so this is also the screen workarea.
        # (with more monitors, merging them would just lose the panels we care about)
        return gtk_workareas[0]
    desktop = get_current_desktop()
    workareas = get_net_workareas()
    if desktop < 0 or desktop >= len(workareas):
        root_w, root_h = get_root_size()
        return 0, 0, root_w, root_h
    return workareas[desktop]


def set_desktop_list(desktops: Sequence[str]) -> None:
    log("set_desktop_list(%s)", desktops)
    root_set("_NET_NUMBER_OF_DESKTOPS", "u32", len(desktops))
    root_array_set("_NET_DESKTOP_NAMES", "utf8", desktops)


def set_current_desktop(index: int) -> None:
    root_set("_NET_CURRENT_DESKTOP", "u32", index)


def get_current_desktop() -> int:
    return root_get("_NET_CURRENT_DESKTOP", "u32") or 0


def set_desktop_geometry(width: int, height: int) -> None:
    v = (width, height)
    log("_NET_DESKTOP_GEOMETRY=%s", v)
    root_array_set("_NET_DESKTOP_GEOMETRY", "u32", v)


def get_desktop_geometry() -> tuple[int, int]:
    desktop_geometry = root_array_get("_NET_DESKTOP_GEOMETRY", "u32")
    if desktop_geometry and len(desktop_geometry) == 2:
        return int(desktop_geometry[0]), int(desktop_geometry[1])
    return get_root_size()


def get_number_of_desktops() -> int:
    return root_get("_NET_NUMBER_OF_DESKTOPS", "u32") or 1


# noinspection PyInconsistentReturns
def get_root_size() -> tuple[int, int]:
    with xsync:
        X11Window = X11WindowBindings()
        return X11Window.get_root_size()


def set_desktop_viewport(x=0, y=0) -> None:
    root_array_set("_NET_DESKTOP_VIEWPORT", "u32", (x, y))


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
    data = root_array_get("_ICC_PROFILE", f"u{xformat}") or ()
    if not data:
        return b""
    try:
        return bytes(data)
    except ValueError as e:
        log("get_icc_profile() data=%r", data, exc_info=True)
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

    def __init__(self, props: Iterable[str], prefixes: Iterable[str] = ()):
        super().__init__()
        self._props = props
        # `prefixes` matches families of properties whose name varies at runtime,
        # ie: `_GTK_WORKAREAS_D#` where `#` is the current desktop
        self._prefixes = tuple(prefixes)
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
        atom = str(event.atom)
        if atom in self._props or atom.startswith(self._prefixes):
            self.do_notify(atom)

    def do_notify(self, prop: str) -> None:
        log("XRootPropWatcher.do_notify(%s)", prop)
        self.emit("root-prop-changed", prop)

    def notify_all(self) -> None:
        for prop in self._props:
            self.do_notify(prop)


GObject.type_register(XRootPropWatcher)


def main() -> int:
    from xpra.platform import program_context
    from xpra.log import enable_color, consume_verbose_argv
    with program_context("X11-Root-Properties"):
        enable_color()
        consume_verbose_argv(sys.argv, "all")

        from xpra.x11.bindings.display_source import init_display_source
        init_display_source()

        log.info("net-workareas=%s", get_net_workareas())
        log.info("gtk-workareas=%s", get_gtk_workareas())
        log.info("workareas=%s", get_workareas())
        log.info("workarea=%s", get_workarea())
        log.info("current-desktop=%s", get_current_desktop())
        log.info("desktop-geometry=%s", get_desktop_geometry())
        log.info("number-of-desktops=%s", get_number_of_desktops())
        log.info("root-size=%s", get_root_size())
        log.info("desktop-names=%s", get_desktop_names())
        log.info("icc-profile=%s", get_icc_profile())
        log.info("icc-version=%s", get_icc_version())
        log.info("xkb-rules-names=%s", get_xkb_rules_names())
        log.info("xresources=%s", get_xresources())
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
