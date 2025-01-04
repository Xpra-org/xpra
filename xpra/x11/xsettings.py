# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from typing import Final

from xpra.os_util import gi_import
from xpra.gtk.gobject import no_arg_signal, one_arg_signal
from xpra.gtk.error import xlog, XError
from xpra.x11.bindings.core import X11CoreBindings
from xpra.x11.gtk.prop import raw_prop_set, raw_prop_get
from xpra.x11.gtk.selection import ManagerSelection
from xpra.x11.gtk.bindings import add_event_receiver, remove_event_receiver, get_xatom
from xpra.x11.xsettings_prop import bytes_to_xsettings, xsettings_to_bytes
from xpra.log import Logger

log = Logger("x11", "xsettings")

GObject = gi_import("GObject")
Gtk = gi_import("Gtk")
Gdk = gi_import("Gdk")

X11Core = X11CoreBindings()

# the X11 atom name for the XSETTINGS property:
XSETTINGS: Final[str] = "_XSETTINGS_SETTINGS"
# constant type in prop.py:
XSETTINGS_TYPE: Final[str] = "xsettings-settings"

XNone = 0


class XSettingsManager:
    __slots__ = ("_manager", "_window")

    def __init__(self, screen_number=0):
        selection = f"_XSETTINGS_S{screen_number}"
        self._manager = ManagerSelection(selection)
        # Technically I suppose ICCCM says we should use FORCE, but it's not
        # like a window manager where you have to wait for the old wm to clean
        # things up before you can do anything... as soon as the selection is
        # gone, the settings are gone. (Also, if we're stealing from
        # ourselves, we probably don't clean up the window properly.)
        self._manager.acquire(self._manager.FORCE_AND_RETURN)

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
        atom = Gdk.Atom.intern(self._selection, False)
        self._clipboard = Gtk.Clipboard.get(atom)

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

    def __init__(self, screen_number=0):
        GObject.GObject.__init__(self)
        XSettingsHelper.__init__(self, screen_number)
        self.xid = X11Core.get_root_xid()
        add_event_receiver(self.xid, self)
        self._add_watch()

    def cleanup(self) -> None:
        remove_event_receiver(self.xid, self)

    def _add_watch(self) -> None:
        owner = self.xsettings_owner()
        if owner:
            add_event_receiver(owner, self)

    def do_x11_client_message_event(self, evt) -> None:
        if evt.window is self.xid and evt.message_type == "MANAGER" and evt.data[1] == get_xatom(self._selection):
            log("XSettings manager changed")
            self._add_watch()
            self.emit("xsettings-changed")

    def do_x11_property_notify_event(self, event) -> None:
        if str(event.atom) == XSETTINGS:
            log("XSettings property value changed")
            self.emit("xsettings-changed")


GObject.type_register(XSettingsWatcher)


def main():
    # pylint: disable=import-outside-toplevel
    from xpra.x11.xsettings_prop import XSettingsNames
    from xpra.x11.gtk.display_source import init_gdk_display_source
    init_gdk_display_source()
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
