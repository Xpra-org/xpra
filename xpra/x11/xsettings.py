# This file is part of Xpra.
# Copyright (C) 2010-2023 Antoine Martin <antoine@xpra.org>
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from gi.repository import GObject, Gdk, Gtk  # @UnresolvedImport

from xpra.gtk_common.gobject_util import no_arg_signal, one_arg_signal
from xpra.gtk_common.error import xlog, XError
from xpra.x11.gtk_x11.prop import raw_prop_set, raw_prop_get
from xpra.x11.gtk_x11.selection import ManagerSelection
from xpra.x11.gtk3.gdk_bindings import add_event_receiver, remove_event_receiver, get_pywindow, get_xatom
from xpra.x11.xsettings_prop import bytes_to_xsettings, xsettings_to_bytes
from xpra.log import Logger

log = Logger("x11", "xsettings")

#the X11 atom name for the XSETTINGS property:
XSETTINGS = "_XSETTINGS_SETTINGS"
#constant type in prop.py:
XSETTINGS_TYPE = "xsettings-settings"

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
        self._window = self._manager.window()

    def set_settings(self, settings):
        if isinstance(settings, list):
            settings = tuple(settings)
        elif not isinstance(settings, tuple):
            log.warn("Warning: discarding xsettings because of incompatible format: %s", type(settings))
            return
        try:
            data = xsettings_to_bytes(settings)
            raw_prop_set(self._window.get_xid(), XSETTINGS, "_XSETTINGS_SETTINGS", 8, data)
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

    def xsettings_owner(self):
        with xlog:
            from xpra.x11.bindings.window import X11WindowBindings #@UnresolvedImport
            X11Window = X11WindowBindings()
            owner_x = X11Window.XGetSelectionOwner(self._selection)
            log("XGetSelectionOwner(%s)=%#x", self._selection, owner_x)
            if owner_x == XNone:
                return None
            return get_pywindow(owner_x)

    def get_settings(self):
        owner = self.xsettings_owner()
        log("Fetching current XSettings data, owner=%s", owner)
        if owner is None:
            return None
        data = raw_prop_get(owner.get_xid(), XSETTINGS, "_XSETTINGS_SETTINGS", ignore_errors=True, raise_xerrors=False)
        if data:
            return bytes_to_xsettings(data)
        return None


class XSettingsWatcher(XSettingsHelper, GObject.GObject):
    __gsignals__ = {
        "xsettings-changed": no_arg_signal,

        "xpra-property-notify-event": one_arg_signal,
        "xpra-client-message-event": one_arg_signal,
        }
    def __init__(self, screen_number=0):
        GObject.GObject.__init__(self)
        XSettingsHelper.__init__(self, screen_number)
        root = self._clipboard.get_display().get_default_screen().get_root_window()
        self.xid = root.get_xid()
        add_event_receiver(self.xid, self)
        self._add_watch()

    def cleanup(self):
        remove_event_receiver(self.xid, self)

    def _add_watch(self):
        owner = self.xsettings_owner()
        if owner is not None:
            add_event_receiver(owner.get_xid(), self)

    def do_xpra_client_message_event(self, event):
        if (event.window is self.xid
            and event.message_type == "MANAGER"
            and event.data[1] == get_xatom(self._selection)):
            log("XSettings manager changed")
            self._add_watch()
            self.emit("xsettings-changed")

    def do_xpra_property_notify_event(self, event):
        if str(event.atom) == XSETTINGS:
            log("XSettings property value changed")
            self.emit("xsettings-changed")

GObject.type_register(XSettingsWatcher)


def main():
    # pylint: disable=import-outside-toplevel
    from xpra.x11.xsettings_prop import XSettingsNames
    from xpra.x11.gtk3.gdk_display_source import init_gdk_display_source
    init_gdk_display_source()
    s = XSettingsHelper().get_settings()
    assert s
    seq, data = s
    print(f"XSettings: (sequence {seq})")
    for vtype, prop, value, serial  in data:
        if isinstance(value, bytes):
            vstr = value.decode()
        else:
            vstr = str(value)
        if serial>0:
            vstr += f" (serial={serial:x})"
        print("%8s: %32s = %-32s" % (XSettingsNames.get(vtype, "?"), prop.decode(), vstr))


if __name__ == "__main__":
    main()
