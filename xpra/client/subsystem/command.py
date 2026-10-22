# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from typing import Any
from collections.abc import Sequence

from xpra.client.base.stub import StubClientSubsystem
from xpra.common import noop, may_notify_client
from xpra.constants import NotificationID
from xpra.net.packet_type import COMMAND_START
from xpra.util.env import envint, first_time
from xpra.util.parsing import str_to_bool
from xpra.util.objects import typedict
from xpra.util.str_fn import bytestostr, single_line, truncate
from xpra.log import Logger

log = Logger("exec")

MAX_MENU_CATEGORIES = envint("XPRA_MAX_MENU_CATEGORIES", 16)
MAX_MENU_ENTRIES = envint("XPRA_MAX_MENU_ENTRIES", 32)
MAX_MENU_NAME = 64


def menu_name(name) -> str:
    return truncate(single_line(bytestostr(name)).strip(), MAX_MENU_NAME)


def validated_menu(menu) -> tuple[dict, bool]:
    """
    the start menu data comes from the server:
    clean the names, and limit the number of categories and of entries in each category
    returns the menu, and whether we had to drop anything
    """
    if not isinstance(menu, dict):
        return {}, False
    trimmed = False
    categories = sorted((menu_name(category), props) for category, props in menu.items() if isinstance(props, dict))
    if len(categories) > MAX_MENU_CATEGORIES:
        log.warn("Warning: the server's start menu has too many categories")
        log.warn(" only using the first %i out of %i", MAX_MENU_CATEGORIES, len(categories))
        categories = categories[:MAX_MENU_CATEGORIES]
        trimmed = True
    validated = {}
    for category, props in categories:
        entries = props.get("Entries")
        if isinstance(entries, dict):
            entries = sorted((menu_name(name), cp) for name, cp in entries.items() if isinstance(cp, dict))
            if len(entries) > MAX_MENU_ENTRIES:
                log.warn("Warning: the server's start menu category %r has too many entries", category)
                log.warn(" only using the first %i out of %i", MAX_MENU_ENTRIES, len(entries))
                entries = entries[:MAX_MENU_ENTRIES]
                trimmed = True
            props = dict(props) | {"Entries": dict(entries)}
        validated[category] = props
    return validated, trimmed


class CommandClient(StubClientSubsystem):
    """
    Utility mixin for clients that execute remote commands
    """
    __slots__ = (
        "request_start", "request_start_child", "server_commands_info", "server_commands_signals",
        "server_menu", "server_start_new_commands", "start_new_commands",
    )
    PREFIX = "command"

    def __init__(self, client=None):
        StubClientSubsystem.__init__(self, client)
        self.server_start_new_commands: bool = False
        self.server_menu = {}
        self.start_new_commands: bool = False
        self.server_commands_info = False
        self.server_commands_signals: Sequence[str] = ()
        self.request_start = []
        self.request_start_child = []

    def init(self, opts) -> None:
        self.start_new_commands = str_to_bool(opts.start_new_commands)
        if self.start_new_commands and (opts.start or opts.start_child):
            from xpra.scripts.args import strip_defaults_start_child
            from xpra.config.defaults import make_defaults_struct
            defaults = make_defaults_struct()
            self.request_start = strip_defaults_start_child(opts.start, defaults.start)
            self.request_start_child = strip_defaults_start_child(opts.start_child, defaults.start_child)

    def get_info(self) -> dict[str, dict[str, Any]]:
        return {}

    def get_caps(self) -> dict[str, Any]:
        caps: dict[str, Any] = {
            # v6.4:
            "menu": self.start_new_commands,
        }
        return caps

    def parse_server_capabilities(self, c: typedict) -> bool:
        self.server_start_new_commands = c.boolget("start-new-commands")
        if self.server_start_new_commands:
            # weak dependency injection on ui client:
            onchange = getattr(self.client, "on_server_setting_changed", noop)

            def update_menu_value(_setting, menu) -> None:
                self.server_menu, trimmed = validated_menu(menu)
                if trimmed and first_time("start-menu-trimmed"):
                    may_notify_client(self.client, NotificationID.MENU, "Start menu is incomplete",
                                      "The server's start menu is too big, some of its entries are not shown",
                                      icon_name="start")
            onchange("menu", update_menu_value)

        if self.request_start or self.request_start_child:
            if self.server_start_new_commands:
                self.client.after_handshake(self.send_start_new_commands)
            else:
                log.warn("Warning: cannot start new commands")
                log.warn(" the feature is currently disabled on the server")
        self.server_commands_info = c.boolget("server-commands-info")
        self.server_commands_signals = c.strtupleget("server-commands-signals")
        return True

    def send_start_new_commands(self) -> None:
        log(f"send_start_new_commands() {self.request_start=}, {self.request_start_child=}")
        import shlex
        for cmd in self.request_start:
            cmd_parts = shlex.split(cmd)
            self.send_start_command(cmd_parts[0], cmd_parts, True)
        for cmd in self.request_start_child:
            cmd_parts = shlex.split(cmd)
            self.send_start_command(cmd_parts[0], cmd_parts, False)

    def send_start_command(self, name: str, command: list[str], ignore: bool, sharing: bool = True) -> None:
        log("send_start_command%s", (name, command, ignore, sharing))
        assert name is not None and command is not None and ignore is not None
        self.send(COMMAND_START, name, command, ignore, sharing)
