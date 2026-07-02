# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from typing import Any

from xpra.net.common import Packet
from xpra.net.packet_type import BELL_SET
from xpra.util.objects import typedict
from xpra.client.base.stub import StubClientMixin
from xpra.log import Logger

log = Logger("window")


class WindowBell(StubClientMixin):
    """
    Bell forwarding. Part of the `window` subsystem, which owns the
    "bell-toggled" signal (see `WindowManagerClient`): peers subscribe with
    `get_subsystem("window").connect("bell-toggled", handler)`.
    """

    def __init__(self):
        if not hasattr(self, "client"):
            StubClientMixin.__init__(self)
        self.client_supports_bell: bool = False
        self.server_bell: bool = False
        self.bell_enabled: bool = False

    def init(self, opts) -> None:
        self.client_supports_bell = opts.bell

    def set_bell_enabled(self, enabled: bool) -> None:
        # toggle bell forwarding, tell the server, and let peers (ie: the tray
        # menu checkbox) sync via the "bell-toggled" signal:
        if not (self.server_bell and self.client_supports_bell):
            return
        if enabled == self.bell_enabled:
            return
        self.bell_enabled = enabled
        self.send(BELL_SET, enabled)
        self.emit("bell-toggled")

    def get_caps(self) -> dict[str, Any]:
        return {
            "bell": self.client_supports_bell,
        }

    def parse_server_capabilities(self, c: typedict) -> bool:
        self.server_bell = c.boolget("bell")  # added in 0.5, default to True!
        self.bell_enabled = self.server_bell and self.client_supports_bell
        return True

    def _process_window_bell(self, packet: Packet) -> None:
        if not self.bell_enabled:
            return
        wid = packet.get_wid()
        device = packet.get_u16(2)
        percent = packet.get_i8(3)
        pitch = packet.get_i32(4)
        duration = packet.get_i32(5)
        bell_class = packet.get_u32(6)
        bell_id = packet.get_u32(7)
        bell_name = packet.get_str(8)
        window = self.get_window(wid)
        self.client.window_bell(window, device, percent, pitch, duration, bell_class, bell_id, bell_name)

    def window_bell(self, window, device: int, percent: int, pitch: int, duration: int, bell_class,
                    bell_id: int, bell_name: str) -> None:
        raise NotImplementedError()

    def init_authenticated_packet_handlers(self) -> None:
        self.add_legacy_alias("bell", "window-bell")
        self.add_packets("window-bell", main_thread=True)
