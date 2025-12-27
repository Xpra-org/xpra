# This file is part of Xpra.
# Copyright (C) 2025 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import signal
from typing import Any
from ctypes import wintypes, byref
from collections.abc import Sequence

from xpra.exit_codes import ExitValue
from xpra.os_util import gi_import
from xpra.util.gobject import no_arg_signal
from xpra.client.base.gobject import GObjectXpraClient
from xpra.client.gui.ui_client_base import UIXpraClient
from xpra.platform.win32.common import GetCursorPos
from xpra.log import Logger

log = Logger("client")
netlog = Logger("client", "network")

GLib = gi_import("GLib")
GObject = gi_import("GObject")


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
        pos = wintypes.POINT()
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

    def get_client_window_classes(self, _geom, _metadata, _override_redirect) -> Sequence[type]:
        from xpra.client.win32.window import ClientWindow
        return (ClientWindow, )

    def register_window(self, wid: int, window) -> None:
        super().register_window(wid, window)
        window.connect("mapped", self.window_mapped)
        window.connect("focused", self.window_focused)
        window.connect("lost-focus", self.window_lost_focus)
        window.connect("moved", self.window_moved)
        window.connect("resized", self.window_resized)
        window.connect("mouse-move", self.window_mouse_moved)
        window.connect("mouse-click", self.window_mouse_clicked)
        window.connect("wheel", self.window_wheel)
        window.connect("key", self.window_key)
        window.create()

    def window_mapped(self, window) -> None:
        log("window_mapped(%s)", window)
        self.send("map-window", window.wid, window.x, window.y, window.width, window.height, {}, {})

    def window_focused(self, window) -> None:
        log("window_focused(%s)", window)
        self.update_focus(window.wid, True)

    def window_lost_focus(self, window) -> None:
        log("window_lost_focus(%s)", window)
        self.update_focus(window.wid, False)

    def window_moved(self, window) -> None:
        log("window_moved(%s)", window)
        self.send_configure(window)

    def window_resized(self, window) -> None:
        log("window_resized(%s)", window)
        self.send_configure(window)

    def send_configure(self, window) -> None:
        props = {}
        resize_counter = 0
        state = {}
        skip_geometry = False
        packet = [window.wid, window.x, window.y, window.width, window.height, props, resize_counter, state, skip_geometry]
        # pwid = window.wid
        # if False: # self.is_OR():
        #    pwid = -1 if BACKWARDS_COMPATIBLE else 0
        # packet.append(pwid)
        # packet.append(self.get_mouse_position())
        # packet.append(self._client.get_current_modifiers())
        log.warn("send_configure: geometry=%s", (window.x, window.y, window.width, window.height))
        self.send("configure-window", *packet)

    def window_mouse_moved(self, window, x: int, y: int, vk: Sequence[str], buttons: Sequence[int]) -> None:
        log.warn("window_mouse_moved(%s, %i, %i, %s, %s)", window, x, y, vk, buttons)
        device_id = -1
        modifiers = vk
        props = {}
        pos = (x, y, x - window.x, y-window.y)
        self.send_mouse_position(device_id, window.wid, pos, modifiers=modifiers, buttons=buttons, props=props)

    def window_mouse_clicked(self, window, button, pressed, x: int, y: int, vk: Sequence[str], buttons: Sequence[int]) -> None:
        log.warn("window_mouse_clicked(%s, %i, %i, %s, %s)", window, x, y, vk, buttons)
        device_id = -1
        modifiers = vk
        props = {}
        pos = (x, y, x - window.x, y-window.y)
        self.send_button(device_id, window.wid, button, pressed, pos, modifiers=modifiers, buttons=buttons, props=props)

    def window_wheel(self, window, x: int, y: int, vertical: bool, vk: Sequence[str], delta: int) -> None:
        log.warn("window_wheel(%s, %i, %i, %s, %s, %s)", window, x, y, vertical, vk, delta)
        device_id = -1
        props = {}
        pos = (x, y, x - window.x, y - window.y)
        wheel_delta = self.wheel_delta + delta
        button = 4 if wheel_delta > 0 else 5
        if not vertical:
            button += 4
        self.wheel_delta = self.send_wheel_delta(device_id, window.wid, button, abs(wheel_delta), pointer=pos, props=props)

    def window_key(self, window, pressed: bool, vkcode: int, keyname: str, scancode: int) -> None:
        log.warn("window_key(%s, %s, %i, %r, %i)", window, pressed, vkcode, keyname, scancode)


GObject.type_register(XpraWin32Client)


def make_client() -> XpraWin32Client:
    signal.signal(signal.SIGINT, signal.SIG_DFL)
    return XpraWin32Client()
