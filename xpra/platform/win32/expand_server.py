# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os

from xpra.os_util import gi_import
from xpra.scripts.config import InitException
from xpra.constants import XPRA_APP_ID
from xpra.platform.win32.shadow_server import ShadowServer
from xpra.log import Logger

log = Logger("server", "win32")
vddlog = Logger("vdd")

GLib = gi_import("GLib")


def get_initial_resolution() -> tuple[int, int]:
    """Resolution of the virtual monitor created when the server starts."""
    res = os.environ.get("XPRA_EXPAND_RESOLUTION", "1920x1080")
    try:
        w, h = res.lower().split("x", 1)
        return int(w), int(h)
    except ValueError:
        vddlog.warn("Warning: invalid XPRA_EXPAND_RESOLUTION %r, using 1920x1080", res)
        return 1920, 1080


class ExpandServer(ShadowServer):
    """
    Win32 'expand' server.

    Like the shadow server, but it never captures the physical display: it
    exposes only parsec-vdd virtual monitors, which clients add and remove on
    demand (re-using the shadow server's virtual-monitor support).
    """

    def __init__(self, display, attrs: dict[str, str]):
        super().__init__(display, attrs)
        self.session_type = "win32 vdd expand"

    def init(self, opts) -> None:
        super().init(opts)
        # the expand server is useless without the ability to create monitors:
        if not self._vdd_multimonitor:
            raise InitException("the 'expand' server requires the Parsec VDD driver to be installed")

    def add_new_client(self, ss, caps) -> None:
        super().add_new_client(ss, caps)
        # create a virtual monitor when a client connects, rather than plugging
        # in a display while nobody is watching. The guard makes this a no-op
        # when monitors already exist (extra clients, or a still-live session):
        GLib.idle_add(self._add_initial_monitor)

    def _add_initial_monitor(self) -> bool:
        if not self._vdd_displays:
            w, h = get_initial_resolution()
            vddlog.info("expand server: creating initial virtual monitor %ix%i", w, h)
            try:
                self.add_monitor(w, h)
            except Exception:
                vddlog.error("Error: failed to create the initial virtual monitor", exc_info=True)
        return False

    def get_shadow_monitors(self) -> list:
        # only expose the parsec-vdd virtual monitors, never the physical display:
        from xpra.platform.win32.parsecvdd import list_vdd_monitors
        vdd = set(list_vdd_monitors())
        monitors = [m for m in super().get_shadow_monitors() if m[0] in vdd]
        log("expand get_shadow_monitors()=%s (vdd monitors=%s)", monitors, sorted(vdd))
        return monitors

    def make_tray_widget(self):
        from xpra.platform.win32.tray import Win32Tray
        tray = self.get_subsystem("tray")
        menu = getattr(tray, "menu", None)
        return Win32Tray(self, XPRA_APP_ID, menu, "Xpra Expand Server", "server-notconnected",
                         click_cb=self.tray_click_callback, exit_cb=self.tray_exit_callback)
