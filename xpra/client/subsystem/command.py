# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from typing import Any
from collections import Counter
from collections.abc import Sequence

from xpra.client.base.stub import StubClientSubsystem
from xpra.common import noop
from xpra.net.common import BACKWARDS_COMPATIBLE
from xpra.net.packet_type import COMMAND_START
from xpra.util.parsing import str_to_bool
from xpra.util.objects import typedict
from xpra.util.str_fn import bytestostr
from xpra.log import Logger

log = Logger("exec")


def menu_entry_labels(entries: dict) -> dict[str, Any]:
    """
    newer servers key the entries by desktop file id, older ones by name:
    label the entries using their `Name`, falling back to the key,
    and add the key to the labels which are not unique, ie: "Files (nemo)" and "Files (org.gnome.Nautilus)"
    """
    labelled = []
    for key, props in entries.items():
        key = bytestostr(key)
        name = props.get("Name") if isinstance(props, dict) else None
        labelled.append((bytestostr(name or key), key, props))
    counts = Counter(label for label, _key, _props in labelled)
    return {(label if counts[label] == 1 else f"{label} ({key})"): props for label, key, props in labelled}


def labelled_menu(menu) -> dict:
    """ the server's start menu, with the entries keyed by label """
    if not isinstance(menu, dict):
        return {}
    labelled = {}
    for category, props in menu.items():
        if isinstance(props, dict) and isinstance(props.get("Entries"), dict):
            props = dict(props) | {"Entries": menu_entry_labels(props["Entries"])}
        labelled[category] = props
    return labelled


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
            from xpra.scripts.config import make_defaults_struct
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
        if BACKWARDS_COMPATIBLE:
            caps.update({
                # pre-v6.4:
                "xdg-menu": self.start_new_commands,
                # legacy flag:
                "xdg-menu-update": True,
            })
        return caps

    def parse_server_capabilities(self, c: typedict) -> bool:
        self.server_start_new_commands = c.boolget("start-new-commands")
        if self.server_start_new_commands:
            # weak dependency injection on ui client:
            onchange = getattr(self.client, "on_server_setting_changed", noop)

            def update_menu_value(_setting, menu) -> None:
                self.server_menu = labelled_menu(menu)
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
