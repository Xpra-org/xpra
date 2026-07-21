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

from xpra.net.common import BACKWARDS_COMPATIBLE
from xpra.exit_codes import ExitValue
from xpra.net.packet_type import WINDOW_MAP, WINDOW_UNMAP, WINDOW_CLOSE, WINDOW_CONFIGURE
from xpra.os_util import gi_import
from xpra.util.objects import typedict
from xpra.util.gobject import no_arg_signal
from xpra.client.base.gobject import GObjectClientAdapter
from xpra.client.gui.ui_client_base import UIXpraClient
from xpra.client.win32.subsystem.display import Win32DisplayClient
from xpra.platform.gui import get_xdpi, get_ydpi
from xpra.platform.win32.common import GetCursorPos, MessageBeep, GetKeyState, ClientToScreen
from xpra.platform.win32.dpi import physical_point
from xpra.platform.win32.gui import pointer_grab, pointer_ungrab
from xpra.platform.win32.keyboard import VK_NAMES, NATIVE_HELD_VKS, NATIVE_TOGGLED_VKS
from xpra.log import Logger

log = Logger("client")
netlog = Logger("client", "network")
keylog = Logger("client", "keyboard")
grablog = Logger("client", "grab")

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


def get_native_modifiers() -> dict[str, list[str]]:
    held: list[str] = []
    for vk in NATIVE_HELD_VKS:
        if GetKeyState(vk) & 0x8000:
            held.append(VK_NAMES.get(vk, f"VK_{vk:#04x}"))
    toggled: list[str] = []
    for vk in NATIVE_TOGGLED_VKS:
        if GetKeyState(vk) & 0x0001:
            toggled.append(VK_NAMES.get(vk, f"VK_{vk:#04x}"))
    return {"held": held, "toggled": toggled}


class XpraWin32Client(GObjectClientAdapter, UIXpraClient):

    __gsignals__ = {}
    # add signals from super classes (all no-arg signals)
    for signal_name in UIXpraClient.__signals__:
        __gsignals__[signal_name] = no_arg_signal

    @staticmethod
    def get_subsystem_classes() -> dict[str, type]:
        classes = dict(UIXpraClient.get_subsystem_classes())
        classes["display"] = Win32DisplayClient
        return classes

    def __init__(self):
        GObjectClientAdapter.__init__(self)
        UIXpraClient.__init__(self)
        self.win32_message_source = 0
        self.wheel_delta = 0
        self._grab_handle = 0
        self.client_type = "win32"
        # connect the win32 window signals + create the native window for each new window:
        if window := self.get_subsystem("window"):
            window.connect("new-window", self._new_window)

    def __repr__(self):
        return "XpraWin32Client"

    def run(self) -> ExitValue:
        UIXpraClient.run(self)
        return GObjectClientAdapter.run(self)

    def run_loop(self) -> None:
        from xpra.client.win32.glib import inject_windows_message_source
        inject_windows_message_source(self.main_loop)
        GObjectClientAdapter.run_loop(self)

    def cleanup(self) -> None:
        if wms := self.win32_message_source:
            self.win32_message_source = 0
            GLib.source_remove(wms)
        UIXpraClient.cleanup(self)

    def client_toolkit(self) -> str:
        return "Win32"

    def get_current_modifiers(self) -> Sequence[str]:
        return ()

    def get_mouse_position(self) -> tuple:
        pos = POINT()
        GetCursorPos(byref(pos))
        return pos.x, pos.y

    def set_windows_cursor(self, windows, cursor_data):
        log("set_windows_cursor(%s, %s) not implemented in this backend", windows, cursor_data)

    def window_grab(self, wid: int, window) -> None:
        # confine the pointer to the window (via `ClipCursor`):
        handle = window.get_window_handle()
        grabbed = pointer_grab(handle)
        grablog("window_grab(%#x, %s) handle=%#x, pointer_grab=%s", wid, window, handle, grabbed)
        self._grab_handle = handle
        # also grab the keyboard so the user can't Alt-Tab / Super away:
        # (the `WH_KEYBOARD_LL` hook swallows Win/Tab keys while `grabbed` and focused)
        if kb := self.get_subsystem("keyboard"):
            kb.grabbed = True
        if w := self.get_subsystem("window"):
            w._window_with_grab = wid

    def window_ungrab(self) -> None:
        grablog("window_ungrab() handle=%#x", self._grab_handle)
        pointer_ungrab(self._grab_handle)
        self._grab_handle = 0
        if kb := self.get_subsystem("keyboard"):
            kb.grabbed = False
        if w := self.get_subsystem("window"):
            w._window_with_grab = 0

    def init(self, opts) -> None:
        UIXpraClient.init(self, opts)

    def get_group_leader(self, wid: int, metadata: typedict, _override_redirect: bool):
        return None

    def destroy_window(self, wid: int, window) -> None:
        # `destroy_all_windows()` calls this via `self.client`, so the backend can
        # augment the teardown; win32 has no group leaders (see `get_group_leader`),
        # so we just delegate to the window subsystem, which calls `window.destroy()`
        # (triggering the native `DestroyWindow` + GDI cleanup) and handles grab state:
        if w := self.get_subsystem("window"):
            w.destroy_window(wid, window)

    def get_xdpi(self) -> int:
        xdpi = get_xdpi()
        if xdpi > 0:
            return xdpi
        return 96

    def get_ydpi(self) -> int:
        ydpi = get_ydpi()
        if ydpi > 0:
            return ydpi
        return 96

    def get_gl_client_window_module(self, enable_opengl: str) -> tuple[dict, Any]:
        # the native (Gtk-free) WGL OpenGL backend for this client;
        # the `opengl` subsystem calls this from its `init_opengl`:
        from xpra.client.win32.opengl import get_gl_client_window_module
        return get_gl_client_window_module(enable_opengl)

    def get_client_window_classes(self, _geom, _metadata, _override_redirect) -> Sequence[type]:
        from xpra.client.win32.window import ClientWindow
        gl = self.get_subsystem("opengl")
        gl_window_class = gl.GLClientWindowClass if (gl and gl.enabled) else None
        if gl_window_class:
            # try the OpenGL window first, fall back to the GDI window:
            return (gl_window_class, ClientWindow)
        return (ClientWindow, )

    @staticmethod
    def get_menu_helper_class():
        from xpra.client.win32.menu import TrayMenu
        return TrayMenu

    def _new_window(self, _emitter, window) -> None:
        # the `window` subsystem does the id bookkeeping and fires "new-window";
        # connect the win32 window signals and create the native window:
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
        geometry = (window.x, window.y, window.width, window.height)
        if display := self.get_subsystem("display"):
            geometry = display.crect(*geometry)
        packet = [WINDOW_MAP, window.wid, *geometry, {}, {}]
        if monitor := self.get_monitor_position(window):
            packet.append(monitor)
        self.send(*packet)

    def window_closed(self, window) -> None:
        log("window_closed(%s)", window)
        self.send(WINDOW_CLOSE, window.wid)

    def window_focused_event(self, window) -> None:
        log("window_focused_event(%s)", window)
        if not window.is_OR() and (w := self.get_subsystem("window")):
            w.update_focus(window.wid, True)

    def window_focus_lost_event(self, window) -> None:
        log("window_lost_focus(%s)", window)
        if not window.is_OR() and (w := self.get_subsystem("window")):
            w.update_focus(window.wid, False)

    def window_minimized_event(self, window) -> None:
        self.send(WINDOW_UNMAP, window.wid)

    def window_maximized_event(self, window) -> None:
        if not window.state_updates:
            return
        self.send(WINDOW_CONFIGURE, window.wid, {
            "state": window.state_updates,
        })
        # we have consumed it, so we can reset it now:
        window.state_updates = {}

    def window_moved_event(self, window) -> None:
        log("window_moved_event(%s)", window)
        self.send_configure(window)

    def window_resized_event(self, window) -> None:
        log("window_resized_event(%s)", window)
        self.send_configure(window)

    def send_configure(self, window) -> None:
        geometry = (window.x, window.y, window.width, window.height)
        if display := self.get_subsystem("display"):
            geometry = display.crect(*geometry)
        log("send_configure: geometry=%s", geometry)
        config = {
            "state": window.state_updates,
            "geometry": geometry,
            "resize-counter": window.resize_counter,
        }
        if monitor := self.get_monitor_position(window):
            config["monitor"] = monitor
        self.send(WINDOW_CONFIGURE, window.wid, config)
        # we have consumed it, so we can reset it now:
        window.state_updates = {}

    def get_monitor_position(self, window) -> dict[str, Any]:
        monitor = window.get_monitor_position()
        if not monitor:
            return {}
        if display := self.get_subsystem("display"):
            monitor["position"] = display.cp(*monitor["position"])
        return monitor

    def _pointer_data(self, window, x: int, y: int) -> tuple[int, int, int, int]:
        hwnd = window.hwnd
        # screen ("root") position of the client-area origin and of the pointer.
        # `ClientToScreen` transforms the POINT in place, so it must be seeded
        # with the client coordinates we want to convert:
        origin = POINT(0, 0)
        ptr = POINT(x, y)
        if hwnd and ClientToScreen(hwnd, byref(origin)) and ClientToScreen(hwnd, byref(ptr)):
            # Layer 2: normalize to true physical device pixels, so the values
            # are correct even if the process somehow ended up with a lower DPI
            # awareness than Per-Monitor-v2 (a no-op when fully aware):
            ox, oy = physical_point(hwnd, origin.x, origin.y)
            absx, absy = physical_point(hwnd, ptr.x, ptr.y)
            # window-relative coordinates, normalized the same way:
            x, y = absx - ox, absy - oy
        else:
            absx, absy = window.x + x, window.y + y
        display = self.get_subsystem("display")
        if display:
            absx, absy = display.cp(absx, absy)
            x, y = display.cp(x, y)
        return absx, absy, x, y

    def window_mouse_moved_event(self, window, x: int, y: int, vk: Sequence[str], buttons: Sequence[int]) -> None:
        log("window_mouse_moved_event(%s, %i, %i, %s, %s)", window, x, y, vk, buttons)
        device_id = -1
        modifiers = vk
        props = {}
        pos = self._pointer_data(window, x, y)
        self.get_subsystem("pointer").send_mouse_position(device_id, window.wid, pos, modifiers=modifiers, buttons=buttons, props=props)

    def window_mouse_clicked_event(self, window, button, pressed, x: int, y: int, vk: Sequence[str], buttons: Sequence[int]) -> None:
        log("window_mouse_clicked_event(%s, %i, %s, %i, %i, %s, %s)", window, button, pressed, x, y, vk, buttons)
        device_id = -1
        modifiers = vk
        props = {}
        pos = self._pointer_data(window, x, y)
        self.get_subsystem("window").send_button(device_id, window.wid, button, pressed, pos, modifiers=modifiers, buttons=buttons, props=props)

    def window_wheel_event(self, window, x: int, y: int, vertical: bool, vk: Sequence[str], delta: int) -> None:
        log("window_wheel_event(%s, %i, %i, %s, %s, %s)", window, x, y, vertical, vk, delta)
        device_id = -1
        props = {}
        pos = self._pointer_data(window, x, y)
        wheel_delta = self.wheel_delta + delta
        button = 4 if wheel_delta > 0 else 5
        if not vertical:
            button += 4
        self.wheel_delta = self.get_subsystem("window").send_wheel_delta(device_id, window.wid, button, abs(wheel_delta), pointer=pos, props=props)

    def window_key_event(self, window, keyname: str, pressed: bool, vk_code: int, string: str, scancode: int, extended: bool) -> None:
        keylog("window_key_event(%s, %r, %s, %i, %r, %i, %s)", window, keyname, pressed, vk_code, string, scancode, extended)
        mods = get_modifiers()
        if BACKWARDS_COMPATIBLE:
            keyval = scancode
            keycode = vk_code
            group = 0
            self.send("key-action", window.wid, keyname, pressed, mods, keyval, string, keycode, group)
        else:
            self.send("keyboard-event", window.wid, keyname, pressed, {
                "modifiers": mods,
                "native-modifiers": get_native_modifiers(),
                "string": string,
                "keyval": scancode,
                "keycode": vk_code,
                "scancode": scancode,
                "vk-code": vk_code,
                "extended": extended,
                "backend": "win32",
            })

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
