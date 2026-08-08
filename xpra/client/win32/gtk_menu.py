# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

"""
The full featured Gtk tray menu, on the native win32 `NotifyIcon` tray.

Only the *menu* is Gtk here: the tray icon stays the native `Win32Tray`, which
behaves far better than Gtk's deprecated `StatusIcon`. Selected by `--tray=gtk`
(and by `--tray=auto` when Gtk loads).

Unlike the native `TrackPopupMenu` menu, this one needs no modal message pump:
it is an ordinary Gtk popup driven by the main loop the backend already runs.
"""

from xpra.util.env import IgnoreWarningsContext
from xpra.platform.win32.common import SetForegroundWindow
from xpra.client.win32.menu import get_systray_hwnd
from xpra.client.gtk3.tray_menu import GTKTrayMenu
from xpra.log import Logger

log = Logger("menu")


class Win32GTKTrayMenu(GTKTrayMenu):

    def __repr__(self):
        return "win32.Win32GTKTrayMenu"

    def do_show_menu(self, button: int, time) -> None:
        # the tray icon belongs to a native window, not to Gtk, so the menu
        # would pop up behind whatever is in front and never lose focus:
        # take the foreground first (Windows allows it right after a tray click).
        # There may be no tray at all - this menu is also used for the window
        # shortcut - in which case there is nothing to raise:
        if hwnd := get_systray_hwnd(self.client, warn=False):
            SetForegroundWindow(hwnd)
        log("do_show_menu(%s, %s) menu=%s", button, time, self.menu)
        with IgnoreWarningsContext():
            self.menu.popup(None, None, None, None, button, time)
