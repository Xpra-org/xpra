# This file is part of Xpra.
# Copyright (C) 2010-2019 Antoine Martin <antoine@xpra.org>
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.gtk_common.gtk_util import GetClipboard
from xpra.gtk_common.gobject_util import no_arg_signal, one_arg_signal
from xpra.gtk_common.error import xlog, XError
from xpra.x11.gtk_x11.prop import prop_set, prop_get
from xpra.x11.gtk_x11.selection import ManagerSelection
from xpra.x11.gtk_x11.gdk_bindings import (
    add_event_receiver,          #@UnresolvedImport
    remove_event_receiver,       #@UnresolvedImport
    get_pywindow,                #@UnresolvedImport
    get_xatom,                   #@UnresolvedImport
    )
from xpra.gtk_common.gobject_compat import import_gobject
from xpra.log import Logger

gobject = import_gobject()

log = Logger("x11", "xsettings")

#the X11 atom name for the XSETTINGS property:
XSETTINGS = "_XSETTINGS_SETTINGS"
#constant type in prop.py:
XSETTINGS_TYPE = "xsettings-settings"

XNone = 0


class XSettingsManager(object):
    def __init__(self, screen_number=0):
        selection = "_XSETTINGS_S%i" % screen_number
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
            prop_set(self._window, XSETTINGS, XSETTINGS_TYPE, settings)
        except XError as e:
            log.error("Error: XSettings not applied")
            log.error(" %s", e)


class XSettingsHelper(object):
    """
        Convenience class for accessing XSETTINGS,
        without all the code from the watcher.
    """
    def __init__(self, screen_number=0):
        self._selection = "_XSETTINGS_S%s" % screen_number
        self._clipboard = GetClipboard(self._selection)

    def xsettings_owner(self):
        with xlog:
            from xpra.x11.bindings.window_bindings import X11WindowBindings #@UnresolvedImport
            X11Window = X11WindowBindings()
            owner_x = X11Window.XGetSelectionOwner(self._selection)
            log("XGetSelectionOwner(%s)=%#x", self._selection, owner_x)
            if owner_x == XNone:
                return None
            return get_pywindow(self._clipboard, owner_x)

    def get_settings(self):
        owner = self.xsettings_owner()
        log("Fetching current XSettings data, owner=%s", owner)
        if owner is None:
            return None
        try:
            return prop_get(owner, XSETTINGS, XSETTINGS_TYPE)
        except XError:
            log("X error while fetching XSettings data; ignored")
            return None


class XSettingsWatcher(XSettingsHelper, gobject.GObject):
    __gsignals__ = {
        "xsettings-changed": no_arg_signal,

        "xpra-property-notify-event": one_arg_signal,
        "xpra-client-message-event": one_arg_signal,
        }
    def __init__(self, screen_number=0):
        gobject.GObject.__init__(self)
        XSettingsHelper.__init__(self, screen_number)
        self._root = self._clipboard.get_display().get_default_screen().get_root_window()
        add_event_receiver(self._root, self)
        self._add_watch()

    def cleanup(self):
        remove_event_receiver(self._root, self)

    def _add_watch(self):
        owner = self.xsettings_owner()
        if owner is not None:
            add_event_receiver(owner, self)

    def do_xpra_client_message_event(self, event):
        if (event.window is self._root
            and event.message_type == "MANAGER"
            and event.data[1] == get_xatom(self._selection)):
            log("XSettings manager changed")
            self._add_watch()
            self.emit("xsettings-changed")

    def do_xpra_property_notify_event(self, event):
        if str(event.atom) == XSETTINGS:
            log("XSettings property value changed")
            self.emit("xsettings-changed")

gobject.type_register(XSettingsWatcher)


def main():
    from xpra.x11.xsettings_prop import XSettingsNames
    from xpra.x11.gtk_x11.gdk_display_source import init_gdk_display_source
    init_gdk_display_source()
    s = XSettingsHelper().get_settings()
    assert s
    seq, data = s
    print("XSettings: (sequence %i)" % seq)
    for vtype, prop, value, serial  in data:
        if isinstance(value, bytes):
            vstr = value.decode()
        else:
            vstr = str(value)
        if serial>0:
            vstr += " (serial=%#x)" % serial
        print("%8s: %32s = %-32s" % (XSettingsNames.get(vtype, "?"), prop.decode(), vstr))


if __name__ == "__main__":
    main()
