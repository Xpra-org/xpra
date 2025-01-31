# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from typing import Any

from xpra.net.common import PacketType
from xpra.util.objects import typedict
from xpra.server.mixins.stub_server_mixin import StubServerMixin
from xpra.log import Logger

log = Logger("cursor")


class CursorManager(StubServerMixin):
    """
    Mixin for servers that handle cursors.
    """

    def __init__(self):
        self.cursors = False
        self.cursor_size = 0

    def init(self, opts) -> None:
        self.cursors = opts.cursors

    def add_new_client(self, ss, c: typedict, send_ui: bool, share_count: int) -> None:
        if not send_ui:
            return
        if share_count > 0:
            self.cursor_size = 24
        else:
            self.cursor_size = c.intget("cursor.size", 0)

    def send_initial_data(self, ss, caps, send_ui: bool, share_count: int) -> None:
        if not send_ui:
            return
        self.send_initial_cursors(ss, share_count > 0)

    def send_initial_cursors(self, ss, sharing=False) -> None:
        log("send_initial_cursors(%s, %s)", ss, sharing)
        from xpra.server.source.cursors import CursorsMixin
        if isinstance(ss, CursorsMixin):
            ss.send_cursor()

    def get_caps(self, source) -> dict[str, Any]:
        return {
            "cursors": self.cursors,
        }

    def get_info(self, _proto) -> dict[str, Any]:
        return {
            "cursors": {
                "": self.cursors,
                "size": self.cursor_size,
            },
        }

    def _process_set_cursors(self, proto, packet: PacketType) -> None:
        assert self.cursors, "cannot toggle send_cursors: the feature is disabled"
        ss = self.get_server_source(proto)
        if ss:
            ss.send_cursors = bool(packet[1])

    def init_packet_handlers(self) -> None:
        self.add_packets("set-cursors")
