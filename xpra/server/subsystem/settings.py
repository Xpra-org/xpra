# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from typing import Any
from collections.abc import Callable

from xpra.net.common import BACKWARDS_COMPATIBLE, Packet
from xpra.server.subsystem.stub import StubSubsystem
from xpra.log import Logger

log = Logger("server")

# a setting that clients are allowed to change:
# the `Packet` accessor used to validate the value,
# and the callable which applies it: `apply(source, value)`
ClientSetting = tuple[str, Callable[[Any, Any], None]]


class SettingsServer(StubSubsystem):
    """
    Owns the `setting-change` packet, in both directions:
    it broadcasts server side changes to the clients,
    and applies the changes clients are allowed to make.
    """
    __slots__ = ("client_settings", )
    PREFIX = "setting"

    def __init__(self, server=None):
        super().__init__(server)
        # the allow-list of settings clients may change, see `add_client_setting`:
        self.client_settings: dict[str, ClientSetting] = {}
        self.add_client_setting("readonly", "get_bool", self.set_client_readonly)

    def setting_changed(self, setting: str, value: Any) -> None:
        for ss in self.get_sources_by_type():
            if setting == "readonly":
                value = ss.server_enforced_readonly()
            ss.send_setting_change(setting, value)

    def add_client_setting(self, setting: str, getter: str, apply: Callable[[Any, Any], None]) -> None:
        """
        Allow clients to change `setting` using the `setting-change` packet.
        `getter` is the name of the `Packet` accessor validating the value,
        `apply(source, value)` applies it for the client sending it.
        (subsystems register their own settings via `StubSubsystem.add_client_setting`)
        """
        self.client_settings[setting] = (getter, apply)

    def _process_change(self, proto, packet: Packet) -> None:
        ss = self.get_server_source(proto)
        if not ss:
            return
        setting = packet.get_str(1)
        client_setting = self.client_settings.get(setting)
        if not client_setting:
            log.warn("Warning: client %s tried to change setting %r", ss, setting)
            log.warn(" this setting cannot be modified by clients")
            return
        getter, apply = client_setting
        apply(ss, getattr(packet, getter)(2))

    def set_client_readonly(self, ss, readonly: bool) -> None:
        ss.set_client_readonly(readonly)
        log("client %s toggled readonly=%s", ss, ss.client_readonly)

    def _process_readonly_toggled(self, proto, packet: Packet) -> None:
        # legacy packet, superseded by "setting-change":
        ss = self.get_server_source(proto)
        if ss:
            self.set_client_readonly(ss, packet.get_bool(1))

    def init_packet_handlers(self) -> None:
        self.add_packets(f"{SettingsServer.PREFIX}-change")
        if BACKWARDS_COMPATIBLE:
            self.add_packets("readonly-toggled")
