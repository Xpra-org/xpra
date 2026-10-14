# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import win32con

from xpra.os_util import gi_import
from xpra.util.objects import typedict
from xpra.platform.win32.common import SendMessageW
from xpra.platform.win32.gui import pointer_grab, pointer_ungrab
from xpra.client.win32.system_menu import popup_menu
from xpra.log import Logger

GLib = gi_import("GLib")

log = Logger("keyboard")


def set_clipboard_text(hwnd: int, text: str) -> bool:
    from xpra.platform.win32.common import OpenClipboard, EmptyClipboard, SetClipboardData, CloseClipboard
    from xpra.platform.win32.ctypes_clipboard import alloc_global, free_clipboard_handle
    if not OpenClipboard(hwnd):
        log("OpenClipboard(%#x) failed", hwnd)
        return False
    try:
        if not EmptyClipboard():
            return False
        handle = alloc_global((text + "\0").encode("utf-16-le"))
        if SetClipboardData(win32con.CF_UNICODETEXT, handle):
            return True
        free_clipboard_handle(win32con.CF_UNICODETEXT, handle)
        return False
    finally:
        CloseClipboard()


class ShortcutTarget:
    """
    The keyboard shortcut actions are looked up on the window,
    but the native windows don't implement them (unlike the GTK ones):
    the actions are implemented here for the native windows,
    and anything else is looked up on the window, then on the client,
    ie: `show_menu`, `quit`, `show_shortcuts`
    """

    def __init__(self, client, window):
        self.client = client
        self.window = window

    def __repr__(self):
        return f"ShortcutTarget({self.window})"

    def __getattr__(self, name: str):
        for obj in (self.window, self.client):
            if hasattr(obj, name):
                return getattr(obj, name)
        raise AttributeError(f"no shortcut action {name!r} for {self.window}")

    def void(self, *_args) -> None:
        """
        This method can be used to capture key shortcuts
        without triggering any specific action.
        """

    def show_window_menu(self, *_args) -> None:
        # show the native system menu, which includes xpra's items, as `Alt`+`Space` would
        # (from the main loop since this runs from the window procedure handling the key):
        window = self.window
        hwnd = window.hwnd
        log("show_window_menu() hwnd=%#x", hwnd)
        if not hwnd:
            return

        def show_system_menu() -> bool:
            if window.has_system_menu():
                SendMessageW(hwnd, win32con.WM_SYSCOMMAND, win32con.SC_KEYMENU, ord(" "))
            elif action := popup_menu(hwnd, window.can_show_border(), window.get_menu_states()):
                # undecorated windows don't have a system menu, so we only show xpra's items:
                getattr(self, action)()
            return False
        GLib.idle_add(show_system_menu)

    def toggle_above(self, *_args) -> None:
        window = self.window
        above = not window._above
        log("toggle_above() above=%s", above)
        window.set_metadata(typedict({"above": above}))
        window.state_updates["above"] = above
        self.client.send_configure(window)

    def show_window_info(self, *_args) -> None:
        from xpra.client.win32.gtk import is_loaded
        if is_loaded():
            from xpra.client.gtk3.window.window_info import WindowInfo
            wi = WindowInfo(self.window)
            wi.show()
            return
        # without GTK, there is no dialog: log the information and copy it to the clipboard
        from xpra.client.gui.window.info import window_info_text
        text = window_info_text(self.window.get_window_info())
        log.info("window information for window %i:", self.window.wid)
        for line in text.splitlines():
            log.info(" %s", line)
        if set_clipboard_text(self.window.hwnd, text):
            log.info(" (copied to the clipboard)")

    def toggle_fullscreen(self, *_args) -> None:
        window = self.window
        fullscreen = not window.fullscreen
        log("toggle_fullscreen() fullscreen=%s", fullscreen)
        window.set_fullscreen(fullscreen)
        window.state_updates["fullscreen"] = fullscreen
        self.client.send_configure(window)

    def toggle_keyboard_grab(self, *_args) -> None:
        # while `grabbed`, the `WH_KEYBOARD_LL` hook keeps the Win/Tab keys for the focused window:
        if kb := self.client.get_subsystem("keyboard"):
            kb.grabbed = not kb.grabbed
            log("toggle_keyboard_grab() grabbed=%s", kb.grabbed)

    def toggle_pointer_grab(self, *_args) -> None:
        wm = self.client.get_subsystem("window")
        if not wm:
            return
        handle = self.window.get_window_handle()
        wid = self.window.wid
        if wm.pointer_grabbed == wid:
            pointer_ungrab(handle)
            wm.pointer_grabbed = None
        elif pointer_grab(handle):
            wm.pointer_grabbed = wid
        log("toggle_pointer_grab() handle=%#x, pointer_grabbed=%s", handle, wm.pointer_grabbed)

    def magic_key(self, *args) -> None:
        # only the OpenGL backing renders the border:
        if border := self.window.border:
            border.toggle()
            log("magic_key%s border=%s", args, border)
            self.window.redraw()

    def toggle_debug(self, *_args) -> None:
        # only the OpenGL backing paints the boxes:
        backing = self.window.backing
        log.info("toggling debug on backing %s for window %i", backing, self.window.wid)
        if not backing:
            return
        if backing.paint_box_line_width > 0:
            backing.paint_box_line_width = 0
        else:
            backing.paint_box_line_width = backing.default_paint_box_line_width

    def _change_encoding_setting(self, setting: str, delta: int) -> None:
        enc = self.client.get_subsystem("encoding")
        if not enc:
            return
        if getattr(enc, setting) > 0:
            # change the fixed value:
            setattr(enc, setting, max(1, min(100, getattr(enc, setting) + delta)))
            getattr(enc, f"send_{setting}")()
            log("new %s=%s", setting, getattr(enc, setting))
        else:
            min_setting = f"min_{setting}"
            setattr(enc, min_setting, max(0, min(100, getattr(enc, min_setting) + delta)))
            getattr(enc, f"send_{min_setting}")()
            log("new min-%s=%s", setting, getattr(enc, min_setting))

    def increase_quality(self, *_args) -> None:
        self._change_encoding_setting("quality", 10)

    def decrease_quality(self, *_args) -> None:
        self._change_encoding_setting("quality", -10)

    def increase_speed(self, *_args) -> None:
        self._change_encoding_setting("speed", 10)

    def decrease_speed(self, *_args) -> None:
        self._change_encoding_setting("speed", -10)

    def scaleup(self, *_args) -> None:
        if display := self.client.get_subsystem("display"):
            display.scaleup()

    def scaledown(self, *_args) -> None:
        if display := self.client.get_subsystem("display"):
            display.scaledown()

    def scalingoff(self, *_args) -> None:
        if display := self.client.get_subsystem("display"):
            display.scalingoff()

    def scalereset(self, *_args) -> None:
        if display := self.client.get_subsystem("display"):
            display.scalereset()

    def refresh_window(self, *_args) -> None:
        if wm := self.client.get_subsystem("window"):
            wm.send_refresh(self.window.wid)

    def refresh_all_windows(self, *_args) -> None:
        if wm := self.client.get_subsystem("window"):
            wm.send_refresh_all()

    def next_keyboard_layout(self, update_platform_layout=False) -> None:
        if kb := self.client.get_subsystem("keyboard"):
            kb.next_keyboard_layout(update_platform_layout)
