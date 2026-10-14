# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import win32con

from xpra.os_util import gi_import
from xpra.platform.win32.common import SendMessageW
from xpra.platform.win32.gui import pointer_grab, pointer_ungrab
from xpra.log import Logger

GLib = gi_import("GLib")

log = Logger("keyboard")


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
        # show the native system menu, as `Alt`+`Space` would,
        # (from the main loop since this runs from the window procedure handling the key):
        hwnd = self.window.hwnd
        log("show_window_menu() hwnd=%#x", hwnd)
        if not hwnd:
            return

        def show_system_menu() -> bool:
            SendMessageW(hwnd, win32con.WM_SYSCOMMAND, win32con.SC_KEYMENU, ord(" "))
            return False
        GLib.idle_add(show_system_menu)

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
