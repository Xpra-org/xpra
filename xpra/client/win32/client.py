# This file is part of Xpra.
# Copyright (C) 2025 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import signal
import win32con
from typing import Any
from ctypes import byref
from ctypes.wintypes import POINT
from collections.abc import Sequence

from xpra.exit_codes import ExitValue
from xpra.os_util import gi_import
from xpra.util.gobject import no_arg_signal
from xpra.client.base.gobject import GObjectXpraClient
from xpra.client.gui.ui_client_base import UIXpraClient
from xpra.platform.win32.common import GetCursorPos, MessageBeep, GetKeyState, ClientToScreen
from xpra.log import Logger

log = Logger("client")
netlog = Logger("client", "network")
keylog = Logger("client", "keyboard")

GLib = gi_import("GLib")
GObject = gi_import("GObject")


BELL_MAP: dict[str, int] = {
    "TerminalBell": win32con.MB_ICONEXCLAMATION,
}


def get_modifiers() -> list[str]:
    modifiers = []
    if GetKeyState(win32con.VK_SHIFT) & 0x8000:
        modifiers.append("shift")
    if GetKeyState(win32con.VK_CONTROL) & 0x8000:
        modifiers.append("control")
    if GetKeyState(win32con.VK_MENU) & 0x8000:
        modifiers.append("mod1")  # Alt = mod1 in X11 terminology
    # Check toggle keys (low bit set when toggled on)
    if GetKeyState(win32con.VK_CAPITAL) & 0x0001:
        modifiers.append("lock")  # Caps Lock
    if GetKeyState(win32con.VK_NUMLOCK) & 0x0001:
        modifiers.append("mod2")  # Num Lock
    if GetKeyState(win32con.VK_SCROLL) & 0x0001:
        modifiers.append("mod3")  # Scroll Lock
    return modifiers


class XpraWin32Client(GObjectXpraClient, UIXpraClient):

    __gsignals__ = {}
    # add signals from super classes (all no-arg signals)
    for signal_name in UIXpraClient.__signals__:
        __gsignals__[signal_name] = no_arg_signal

    def __init__(self):
        GObjectXpraClient.__init__(self)
        UIXpraClient.__init__(self)
        self.win32_message_source = 0
        self.wheel_delta = 0
        self.client_type = "win32"

    def __repr__(self):
        return "XpraWin32Client"

    def run(self) -> ExitValue:
        UIXpraClient.run(self)
        return GObjectXpraClient.run(self)

    def run_loop(self) -> None:
        from xpra.client.win32.glib import inject_windows_message_source
        inject_windows_message_source(self.glib_mainloop)
        super().run_loop()

    def cleanup(self) -> None:
        wms = self.win32_message_source
        if wms:
            self.win32_message_source = 0
            GLib.source_remove(wms)
        GObjectXpraClient.cleanup(self)
        UIXpraClient.cleanup(self)

    def client_toolkit(self) -> str:
        return "Win32"

    def get_root_size(self):
        from xpra.platform.win32.gui import get_display_size
        return get_display_size()

    def get_screen_sizes(self, xscale=1.0, yscale=1.0) -> Sequence[tuple[int, int]]:
        return (self.get_root_size(), )

    def get_current_modifiers(self) -> Sequence[str]:
        return ()

    def get_mouse_position(self) -> tuple:
        pos = POINT()
        GetCursorPos(byref(pos))
        return pos.x, pos.y

    def set_windows_cursor(self, windows, cursor_data):
        pass

    def init(self, opts) -> None:
        GObjectXpraClient.init(self, opts)
        UIXpraClient.init(self, opts)

    def make_hello(self) -> dict[str, Any]:
        capabilities = GObjectXpraClient.make_hello(self)
        capabilities |= UIXpraClient.make_hello(self)
        return capabilities

    @staticmethod
    def get_client_window_classes(_geom, _metadata, _override_redirect) -> Sequence[type]:
        from xpra.client.win32.window import ClientWindow
        return (ClientWindow, )

    @staticmethod
    def get_menu_helper_class():
        from xpra.client.win32.menu import TrayMenu
        return TrayMenu

    def register_window(self, wid: int, window) -> None:
        super().register_window(wid, window)
        window.connect("mapped", self.window_mapped_event)
        window.connect("closed", self.window_closed)
        window.connect("focused", self.window_focused_event)
        window.connect("focus-lost", self.window_focus_lost_event)
        window.connect("minimized", self.window_minimized_event)
        window.connect("maximized", self.window_maximized_event)
        window.connect("moved", self.window_moved_event)
        window.connect("resized", self.window_resized_event)
        window.connect("mouse-move", self.window_mouse_moved_event)
        window.connect("mouse-click", self.window_mouse_clicked_event)
        window.connect("wheel", self.window_wheel_event)
        window.connect("key", self.window_key_event)
        window.create()

    def window_mapped_event(self, window) -> None:
        log("window_mapped_event(%s)", window)
        self.send("map-window", window.wid, window.x, window.y, window.width, window.height, {}, {})

    def window_closed(self, window) -> None:
        log("window_closed(%s)", window)
        self.send("close-window", window.wid)

    def window_focused_event(self, window) -> None:
        log("window_focused_event(%s)", window)
        if not window.is_OR():
            self.update_focus(window.wid, True)

    def window_focus_lost_event(self, window) -> None:
        log("window_lost_focus(%s)", window)
        if not window.is_OR():
            self.update_focus(window.wid, False)

    def window_minimized_event(self, window) -> None:
        self.send("unmap-window", window.wid)

    def window_maximized_event(self, window) -> None:
        self.send_configure(window, True)

    def window_moved_event(self, window) -> None:
        log("window_moved_event(%s)", window)
        self.send_configure(window)

    def window_resized_event(self, window) -> None:
        log("window_resized_event(%s)", window)
        self.send_configure(window)

    def send_configure(self, window, skip_geometry=False) -> None:
        props = {}
        resize_counter = 0
        state = window.state_updates
        window.state_updates = {}
        skip_geometry = False
        packet = [window.wid, window.x, window.y, window.width, window.height, props, resize_counter, state, skip_geometry]
        # pwid = window.wid
        # if False: # self.is_OR():
        #    pwid = -1 if BACKWARDS_COMPATIBLE else 0
        # packet.append(pwid)
        # packet.append(self.get_mouse_position())
        # packet.append(self._client.get_current_modifiers())
        log("send_configure: geometry=%s", (window.x, window.y, window.width, window.height))
        self.send("configure-window", *packet)

    def _pointer_data(self, window, x: int, y: int) -> tuple[int, int, int, int]:
        absx = window.x + x
        absy = window.y + y
        coords = POINT()
        if ClientToScreen(window.hwnd, byref(coords)):
            absx = int(coords.x)
            absy = int(coords.y)
        return absx, absy, x, y

    def window_mouse_moved_event(self, window, x: int, y: int, vk: Sequence[str], buttons: Sequence[int]) -> None:
        log("window_mouse_moved_event(%s, %i, %i, %s, %s)", window, x, y, vk, buttons)
        device_id = -1
        modifiers = vk
        props = {}
        pos = self._pointer_data(window, x, y)
        self.send_mouse_position(device_id, window.wid, pos, modifiers=modifiers, buttons=buttons, props=props)

    def window_mouse_clicked_event(self, window, button, pressed, x: int, y: int, vk: Sequence[str], buttons: Sequence[int]) -> None:
        log("window_mouse_clicked_event(%s, %i, %s, %i, %i, %s, %s)", window, button, pressed, x, y, vk, buttons)
        device_id = -1
        modifiers = vk
        props = {}
        pos = self._pointer_data(window, x, y)
        self.send_button(device_id, window.wid, button, pressed, pos, modifiers=modifiers, buttons=buttons, props=props)

    def window_wheel_event(self, window, x: int, y: int, vertical: bool, vk: Sequence[str], delta: int) -> None:
        log("window_wheel_event(%s, %i, %i, %s, %s, %s)", window, x, y, vertical, vk, delta)
        device_id = -1
        props = {}
        pos = self._pointer_data(window, x, y)
        wheel_delta = self.wheel_delta + delta
        button = 4 if wheel_delta > 0 else 5
        if not vertical:
            button += 4
        self.wheel_delta = self.send_wheel_delta(device_id, window.wid, button, abs(wheel_delta), pointer=pos, props=props)

    def window_key_event(self, window, keyname: str, pressed: bool, vk_code: int, string: str, scancode: int) -> None:
        keylog("window_key_event(%s, %r, %s, %i, %r, %i)", window, keyname, pressed, vk_code, string, scancode)
        mods = get_modifiers()
        keyval = scancode
        keycode = vk_code
        group = 0
        self.send("key-action", window.wid, keyname, pressed, mods, keyval, string, keycode, group)

    # server event
    @staticmethod
    def window_bell(window, device: int, percent: int, pitch: int, duration: int, bell_class,
                    bell_id: int, bell_name: str) -> None:
        # how can we use the bell class to choose the type?
        log("window-bell %s, %i, %s", bell_class, bell_id, bell_name)
        bell = BELL_MAP.get(bell_name, win32con.MB_OK)
        MessageBeep(bell)


GObject.type_register(XpraWin32Client)


def make_client() -> XpraWin32Client:
    signal.signal(signal.SIGINT, signal.SIG_DFL)
    return XpraWin32Client()
