# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from typing import Final

from xpra.os_util import gi_import
from xpra.util.gobject import no_arg_signal, one_arg_signal
from xpra.x11.error import xlog, XError, xsync
from xpra.x11.common import X11Event
from xpra.x11.bindings.core import get_root_xid
from xpra.x11.prop import raw_prop_set, raw_prop_get
from xpra.x11.selection.manager import ManagerSelection
from xpra.x11.dispatch import add_event_receiver, remove_event_receiver
from xpra.x11.subsystem.xsettings_prop import bytes_to_xsettings, xsettings_to_bytes
from xpra.log import Logger

log = Logger("x11", "xsettings")

GObject = gi_import("GObject")

# the X11 atom name for the XSETTINGS property:
XSETTINGS: Final[str] = "_XSETTINGS_SETTINGS"
# constant type in prop.py:
XSETTINGS_TYPE: Final[str] = "xsettings-settings"

rxid: Final[int] = get_root_xid()

XNone: Final[int] = 0


class XSettingsManager:
    __slots__ = ("_manager", "_window")

    def __init__(self, screen_number=0):
        self._manager = ManagerSelection(f"_XSETTINGS_S{screen_number}")
        # Technically I suppose ICCCM says we should use FORCE, but it's not
        # like a window manager where you have to wait for the old wm to clean
        # things up before you can do anything... as soon as the selection is
        # gone, the settings are gone. (Also, if we're stealing from
        # ourselves, we probably don't clean up the window properly.)
        self._manager.acquire()

    def set_settings(self, settings) -> None:
        if isinstance(settings, list):
            settings = tuple(settings)
        elif not isinstance(settings, tuple):
            log.warn("Warning: discarding xsettings because of incompatible format: %s", type(settings))
            return
        try:
            data = xsettings_to_bytes(settings)
            raw_prop_set(self._manager.xid, XSETTINGS, "_XSETTINGS_SETTINGS", 8, data)
        except XError as e:
            log("set_settings(%s)", settings, exc_info=True)
            log.error("Error: XSettings not applied")
            log.estr(e)


class XSettingsHelper:
    """
        Convenience class for accessing XSETTINGS,
        without all the code from the watcher.
    """
    def __init__(self, screen_number=0):
        self._selection = "_XSETTINGS_S%s" % screen_number
        with xsync:
            from xpra.x11.bindings.window import X11WindowBindings
            X11Window = X11WindowBindings()
            self._selection_atom = X11Window.get_xatom(self._selection)

    def xsettings_owner(self) -> int:
        with xlog:
            from xpra.x11.bindings.window import X11WindowBindings
            X11Window = X11WindowBindings()
            owner_x = X11Window.XGetSelectionOwner(self._selection)
            log("XGetSelectionOwner(%s)=%#x", self._selection, owner_x)
            if owner_x == XNone:
                return 0
            return owner_x

    def get_settings(self):
        owner = self.xsettings_owner()
        log("Fetching current XSettings data, owner=%s", owner)
        if not owner:
            return None
        data = raw_prop_get(owner, XSETTINGS, "_XSETTINGS_SETTINGS", ignore_errors=True, raise_xerrors=False)
        if data:
            return bytes_to_xsettings(data)
        return None


class XSettingsWatcher(XSettingsHelper, GObject.GObject):
    __gsignals__ = {
        "xsettings-changed": no_arg_signal,

        "x11-property-notify-event": one_arg_signal,
        "x11-client-message-event": one_arg_signal,
    }

    def __init__(self):
        GObject.GObject.__init__(self)
        XSettingsHelper.__init__(self)
        add_event_receiver(rxid, self)
        self._add_watch()

    def cleanup(self) -> None:
        remove_event_receiver(rxid, self)

    def _add_watch(self) -> None:
        owner = self.xsettings_owner()
        if owner:
            add_event_receiver(owner, self)

    def do_x11_client_message_event(self, event: X11Event) -> None:
        if event.window is rxid and event.message_type == "MANAGER" and event.data[1] == self._selection_atom:
            log("XSettings manager changed")
            self._add_watch()
            self.emit("xsettings-changed")

    def do_x11_property_notify_event(self, event: X11Event) -> None:
        if str(event.atom) == XSETTINGS:
            log("XSettings property value changed")
            self.emit("xsettings-changed")


GObject.type_register(XSettingsWatcher)


def main() -> None:
    # pylint: disable=import-outside-toplevel
    from xpra.x11.subsystem.xsettings_prop import XSettingsNames
    from xpra.x11.bindings.display_source import init_display_source
    init_display_source()
    s = XSettingsHelper().get_settings()
    assert s
    seq, data = s
    print(f"XSettings: (sequence {seq})")
    for vtype, prop, value, serial in data:
        if isinstance(value, bytes):
            vstr = value.decode()
        else:
            vstr = str(value)
        if serial > 0:
            vstr += f" (serial={serial:x})"
        print("%8s: %32s = %-32s" % (XSettingsNames.get(vtype, "?"), prop.decode(), vstr))


if __name__ == "__main__":
    main()
