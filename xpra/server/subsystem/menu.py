# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from typing import Any

from xpra.os_util import gi_import
from xpra.net.common import FULL_INFO, BACKWARDS_COMPATIBLE
from xpra.server.common import get_sources_by_type
from xpra.util.thread import start_thread
from xpra.util.str_fn import Ellipsizer
from xpra.server.source.menu import MenuConnection
from xpra.server.subsystem.stub import StubServerMixin
from xpra.log import Logger

GLib = gi_import("GLib")

log = Logger("menu")


def do_send_menu_data(ss, menu) -> None:
    if ss.is_closed():
        return
    assert isinstance(ss, MenuConnection)
    if not getattr(ss, "send_setting_change", False):
        return
    attr = "menu" if ss.menu else "xdg-menu"
    log("do_send_menu_data(%s, %s) attr=%s", ss, Ellipsizer(menu), attr)

    def do_send() -> None:
        ss.send_setting_change(attr, menu)
        log(f"{len(menu)} menu data entries sent to {ss}")
    GLib.idle_add(do_send)


class MenuServer(StubServerMixin):
    """
    Manages application menu data and sends it to connected clients.
    """

    PREFIX = "menu"

    def __init__(self):
        StubServerMixin.__init__(self)
        self.menu_provider = None
        self.menu_enabled: bool = False

    def init(self, opts) -> None:
        self.menu_enabled = opts.start_new_commands
        if self.menu_enabled:
            from xpra.server.menu_provider import get_menu_provider
            self.menu_provider = get_menu_provider()
            self.menu_provider.on_reload.append(self.send_updated_menu)

    def setup(self) -> None:
        if self.menu_provider:
            start_thread(self._threaded_menu_setup, "menu-setup", daemon=True)

    def _threaded_menu_setup(self) -> None:
        self.menu_provider.setup()

    def cleanup(self) -> None:
        if mp := self.menu_provider:
            self.menu_provider = None
            mp.cleanup()

    def _get_menu_data(self) -> dict[str, Any] | None:
        if not self.menu_enabled or not self.menu_provider:
            return None
        return self.menu_provider.get_menu_data()

    def get_caps(self, source) -> dict[str, Any]:
        if not source or not BACKWARDS_COMPATIBLE:
            return {}
        wants = getattr(source, "wants", [])
        if "features" not in wants:
            return {}
        return {
            "xdg-menu": {},
        }

    def send_initial_data(self, ss) -> None:
        if isinstance(ss, MenuConnection):
            start_thread(self.send_menu_data, "send-xdg-menu-data", True, (ss,))

    def send_menu_data(self, ss) -> None:
        if ss.is_closed():
            return
        menu = self._get_menu_data() or {}
        do_send_menu_data(ss, menu)

    def send_updated_menu(self, menu) -> None:
        log("send_updated_menu(%s)", Ellipsizer(menu))
        menu_sources = get_sources_by_type(self, MenuConnection)
        for source in menu_sources:
            do_send_menu_data(source, menu)

    def get_info(self, _proto) -> dict[str, Any]:
        mp = self.menu_provider
        if not mp or not FULL_INFO:
            return {}
        return {
            MenuServer.PREFIX: {
                "start": mp.get_menu_data(remove_icons=True, wait=False) or {},
                "desktop": mp.get_desktop_sessions(remove_icons=True) or {},
            }
        }
