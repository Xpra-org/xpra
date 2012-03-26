# This file is part of Parti.
# Copyright (C) 2008, 2009 Nathaniel Smith <njs@pobox.com>
# Parti is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys
import gtk

import wimpiggy.lowlevel

from wimpiggy.wm import Wm
from wimpiggy.keys import HotkeyManager
from wimpiggy.util import gtk_main_quit_really

from parti.world_organizer import WorldOrganizer
from parti.tray import TraySet
from parti.addons.ipython_embed import spawn_repl_window
from parti.bus import PartiDBusService

if sys.version < '3':
    import codecs
    def u(x):
        return codecs.unicode_escape_decode(x)[0]
else:
    def u(x):
        return x

class Parti(object):
    def __init__(self, options):
        self._wm = Wm("Parti", options.replace)
        self._wm.connect("new-window", self._new_window_signaled)
        self._wm.connect("quit", self._wm_quit)

        self._trays = TraySet()
        self._trays.connect("changed", self._desktop_list_changed)
        
        # Create our display stage
        self._world_organizer = WorldOrganizer(self._trays)
        self._wm.get_property("toplevel").add(self._world_organizer)
        self._world_organizer.show_all()

        ltray = options.tray.lower()
        # __import__ returns topmost module and getattr will not get sub-modules not imported
        # thus (using these two functions) the module path must be specified twice
        dynmodule = getattr(getattr(__import__('parti.trays.' + ltray), 'trays'), ltray)
        dynclass = getattr(dynmodule, options.tray + "Tray")
        self._trays.new(u("default"), dynclass)

        self._root_hotkeys = HotkeyManager(gtk.gdk.get_default_root_window())
        self._root_hotkeys.add_hotkeys({"<shift><alt>r": "repl"})
        self._root_hotkeys.connect("hotkey::repl",
                                   lambda *args: self.spawn_repl_window())

        for window in self._wm.get_property("windows"):
            self._add_new_window(window)

        # Start providing D-Bus api
        self._dbus = PartiDBusService(self)

    def main(self):
        gtk.main()

    def _wm_quit(self, *args):
        gtk_main_quit_really()

    def _new_window_signaled(self, wm, window):
        self._add_new_window(window)

    def _add_new_window(self, window):
        # FIXME: be less stupid
        self._trays.trays[0].add(window)

    def _desktop_list_changed(self, *args):
        self._wm.emit("desktop-list-changed", self._trays.tags())

    def spawn_repl_window(self):
        spawn_repl_window(self._wm,
                          {"parti": self,
                           "wm": self._wm,
                           "windows": self._wm.get_property("windows"),
                           "trays": self._trays,
                           "lowlevel": wimpiggy.lowlevel})

