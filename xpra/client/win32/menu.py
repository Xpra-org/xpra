# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import win32con
from ctypes import byref
from ctypes.wintypes import POINT, HWND

from xpra.platform.win32.common import (
    CreatePopupMenu, AppendMenuW, SetForegroundWindow, TrackPopupMenu, GetCursorPos,
    DestroyMenu, SendMessageW,
)
from xpra.client.win32.glib import start_modal_message_pump, stop_modal_message_pump
from xpra.client.gui.menu_helper import MenuHelper
from xpra.log import Logger

log = Logger("menu")


def get_systray_hwnd(client, warn=True) -> HWND:
    """
    The `HWND` of the native tray icon's window, shared by both menu backends.
    The native menu cannot be shown without it, but the Gtk menu only wants it
    to take the foreground, so it passes `warn=False` (the menu can also be
    triggered from a window shortcut, with no tray involved at all).
    """
    if not client:
        if warn:
            log.warn("Warning: unable to show menu without a client object")
        return 0
    tray_subsystem = client.get_subsystem("tray")
    tray = tray_subsystem.tray if tray_subsystem else None
    if not tray:
        if warn:
            log.warn("Warning: unable to show menu without a tray object")
        return 0
    return tray.getHWND()


class TrayMenu(MenuHelper):

    def __repr__(self):
        return "win32.TrayMenu"

    def setup_menu(self):
        log("setup_menu()")
        menu = CreatePopupMenu()
        AppendMenuW(menu, 0, 1001, "Disconnect")
        AppendMenuW(menu, 0, 1002, "Close")
        return menu

    def get_systray_hwnd(self) -> HWND:
        return get_systray_hwnd(self.client)

    def do_show_menu(self, button: int, time):
        hwnd = self.get_systray_hwnd()
        if not hwnd:
            return
        pos = POINT()
        GetCursorPos(byref(pos))
        SetForegroundWindow(hwnd)
        # `TrackPopupMenu` (with TPM_RETURNCMD) runs its own modal message loop
        # and blocks until the user picks an item or dismisses the menu; keep
        # GLib serviced during that time so screen updates and the UI watcher
        # keep running (the tray window's WndProc is not ours to hook):
        start_modal_message_pump(hwnd)
        try:
            cmd = TrackPopupMenu(self.menu, win32con.TPM_RETURNCMD, pos.x, pos.y, 0, hwnd, None)
        finally:
            stop_modal_message_pump(hwnd)
        # PostMessageA(hwnd, win32con.WM_NULL, 0, 0)
        log("TrackPopupMenu(..)=%s", cmd)
        if cmd == 1001:
            self.client.quit(0)
        elif cmd == 1002:
            self.close_menu()

    def cleanup(self) -> None:
        super().cleanup()
        if menu := self.menu:
            self.menu = 0
            DestroyMenu(menu)

    def close_menu(self) -> None:
        if self.menu_shown:
            hwnd = self.get_systray_hwnd()
            if not hwnd:
                SendMessageW(hwnd, win32con.WM_CANCELMODE, 0, 0)
            self.menu_shown = False
