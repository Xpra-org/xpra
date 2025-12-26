# This file is part of Xpra.
# Copyright (C) 2025 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import signal
from typing import Any
from ctypes import wintypes, byref
from collections.abc import Sequence

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

    def run_loop(self) -> None:
        from xpra.client.win32.glib import inject_windows_message_source
        inject_windows_message_source(self.glib_mainloop)
        super().run_loop()

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


GObject.type_register(XpraWin32Client)


def make_client() -> XpraWin32Client:
    signal.signal(signal.SIGINT, signal.SIG_DFL)
    return XpraWin32Client()
