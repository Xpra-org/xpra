# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from typing import Any
from time import monotonic
from collections.abc import Callable

from xpra.net.common import FULL_INFO, BACKWARDS_COMPATIBLE
from xpra.util.env import envint
from xpra.util.thread import start_thread
from xpra.util.str_fn import Ellipsizer
from xpra.server.source.menu import MenuConnection
from xpra.server.subsystem.stub import StubSubsystem
from xpra.log import Logger

log = Logger("menu")

MENU_SEND_DELAY = envint("XPRA_MENU_SEND_DELAY", 5)


def do_send_menu_data(ss, menu, idle_add: Callable) -> None:
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
    idle_add(do_send)


class MenuServer(StubSubsystem):
    """
    Manages application menu data and sends it to connected clients.
    """
    __slots__ = ("enabled", "last_menu_sent", "pending_menu", "provider", "send_menu_timer")

    PREFIX = "menu"

    def __init__(self, server=None):
        StubSubsystem.__init__(self, server)
        self.provider = None
        self.enabled: bool = False
        self.send_menu_timer = 0
        self.last_menu_sent = 0.0
        self.pending_menu: dict[str, Any] = {}

    def init(self, opts) -> None:
        self.enabled = opts.start_new_commands
        if self.enabled:
            from xpra.server.menu_provider import get_menu_provider
            self.provider = get_menu_provider()
            self.provider.on_reload.append(self.schedule_send_menu)

    def setup(self) -> None:
        if self.provider:
            start_thread(self._threaded_menu_setup, "menu-setup", daemon=True)

    def _threaded_menu_setup(self) -> None:
        self.provider.setup()

    def cleanup(self) -> None:
        self.cancel_send_menu_timer()
        self.pending_menu = {}
        if mp := self.provider:
            self.provider = None
            mp.cleanup()

    def _get_menu_data(self) -> dict[str, Any] | None:
        if not self.enabled or not self.provider:
            return None
        return self.provider.get_menu_data()

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
        do_send_menu_data(ss, menu, self.idle_add)

    def cancel_send_menu_timer(self) -> None:
        if smt := self.send_menu_timer:
            self.send_menu_timer = 0
            self.source_remove(smt)

    def schedule_send_menu(self, menu: dict) -> None:
        self.pending_menu = menu
        if self.send_menu_timer:
            return
        elapsed = round(monotonic() - self.last_menu_sent)
        delay = max(0, MENU_SEND_DELAY - elapsed)
        log("schedule_send_menu(%s) delay=%s", Ellipsizer(menu), delay)
        if delay <= 0:
            self.send_updated_menu()
            return
        self.send_menu_timer = self.timeout_add(int(delay * 1000), self.send_updated_menu)

    def send_updated_menu(self) -> bool:
        self.send_menu_timer = 0
        menu = self.pending_menu
        self.pending_menu = {}
        self.last_menu_sent = monotonic()
        log("send_updated_menu(%s)", Ellipsizer(menu))
        menu_sources = self.get_sources_by_type(MenuConnection)
        for source in menu_sources:
            do_send_menu_data(source, menu, self.idle_add)
        return False

    def get_info(self, _proto) -> dict[str, Any]:
        mp = self.provider
        if not mp or not FULL_INFO:
            return {}
        return {
            MenuServer.PREFIX: {
                "start": mp.get_menu_data(remove_icons=True, wait=False) or {},
                "desktop": mp.get_desktop_sessions(remove_icons=True) or {},
            }
        }
