# This file is part of Xpra.
# Copyright (C) 2010-2013 Antoine Martin <antoine@devloop.org.uk>
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import gobject
import gtk
from xpra.gtk_common.gobject_util import no_arg_signal, one_arg_signal
from xpra.x11.gtk_x11.error import *
from xpra.x11.gtk_x11.selection import ManagerSelection
from xpra.x11.gtk_x11.prop import prop_set, prop_get
from xpra.x11.lowlevel import (
                myGetSelectionOwner,            #@UnresolvedImport
                const, get_pywindow,            #@UnresolvedImport
                add_event_receiver,             #@UnresolvedImport
                get_xatom                       #@UnresolvedImport
                )
from xpra.log import Logger
log = Logger()

#the X11 atom name for the XSETTINGS property:
XSETTINGS = "_XSETTINGS_SETTINGS"
#constant type in prop.py:
XSETTINGS_TYPE = "xsettings-settings"


class XSettingsManager(object):
    def __init__(self, settings_blob, screen_number=0):
        selection = "_XSETTINGS_S%s" % screen_number
        self._manager = ManagerSelection(gtk.gdk.display_get_default(), selection)
        # Technically I suppose ICCCM says we should use FORCE, but it's not
        # like a window manager where you have to wait for the old wm to clean
        # things up before you can do anything... as soon as the selection is
        # gone, the settings are gone. (Also, if we're stealing from
        # ourselves, we probably don't clean up the window properly.)
        self._manager.acquire(self._manager.FORCE_AND_RETURN)
        self._window = self._manager.window()
        self._set_blob_in_place(settings_blob)

    # This is factored out as a separate function to make it easier to test
    # XSettingsWatcher:
    def _set_blob_in_place(self, settings_blob):
        if type(settings_blob)!=tuple:
            log.warn("discarding xsettings because of incompatible format: %s", type(settings_blob))
            return
        prop_set(self._window, XSETTINGS, XSETTINGS_TYPE, settings_blob)

class XSettingsWatcher(gobject.GObject):
    __gsignals__ = {
        "xsettings-changed": no_arg_signal,

        "xpra-property-notify-event": one_arg_signal,
        "xpra-client-message-event": one_arg_signal,
        }
    def __init__(self, screen_number=0):
        gobject.GObject.__init__(self)
        self._selection = "_XSETTINGS_S%s" % screen_number
        self._clipboard = gtk.Clipboard(gtk.gdk.display_get_default(), self._selection)
        self._current = None
        self._root = self._clipboard.get_display().get_default_screen().get_root_window()
        add_event_receiver(self._root, self)
        self._add_watch()

    def _owner(self):
        owner_x = myGetSelectionOwner(self._clipboard, self._selection)
        if owner_x == const["XNone"]:
            return None
        try:
            return trap.call_synced(get_pywindow, self._clipboard, owner_x)
        except XError:
            log("X error while fetching owner of XSettings data; ignored")
            return None

    def _add_watch(self):
        owner = self._owner()
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
        if event.atom == XSETTINGS:
            log("XSettings property value changed")
            self.emit("xsettings-changed")

    def _get_settings_blob(self):
        owner = self._owner()
        if owner is None:
            return None
        return prop_get(owner, XSETTINGS, XSETTINGS_TYPE)

    def get_settings_blob(self):
        log("Fetching current XSettings data")
        try:
            return trap.call_synced(self._get_settings_blob)
        except XError:
            log("X error while fetching XSettings data; ignored")
            return None

gobject.type_register(XSettingsWatcher)
