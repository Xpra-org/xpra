# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from typing import Any

from xpra.net.common import Packet
from xpra.server.subsystem.display import DisplayManager
from xpra.x11.bindings.core import get_root_xid
from xpra.x11.dispatch import add_event_receiver
from xpra.log import Logger

log = Logger("screen")


class BellServer(DisplayManager):
    """
    Servers that forward bell events.
    """
    PREFIX = "bell"

    def __init__(self):
        self.bell = False

    def init(self, opts) -> None:
        self.bell = opts.bell

    def get_caps(self, source) -> dict[str, Any]:
        return self.get_info()

    def get_info(self, _proto) -> dict[str, Any]:
        return {
            "bell": self.bell,
        }

    def setup(self) -> None:
        if self.bell:
            # somewhat redundant, but doing it more than once does not hurt:
            rxid = get_root_xid()
            add_event_receiver(rxid, self)

    def _process_bell_set(self, proto, packet: Packet) -> None:
        assert self.bell, "cannot toggle send_bell: the feature is disabled"
        ss = self.get_server_source(proto)
        if ss:
            ss.send_bell = packet.get_bool(1)

    def do_x11_xkb_event(self, event) -> None:
        if not self.bell:
            return
        # X11: XKBNotify
        log("server do_x11_xkb_event(%r)" % event)
        if event.subtype != "bell":
            log.error(f"Error: unknown event subtype: {event.subtype!r}")
            log.error(f" {event=}")
            return
        # bell events on our windows will come through the bell signal,
        # this method is a catch-all for events on windows we don't manage,
        # so we use wid=0 for that:
        wid = 0
        for ss in self.window_sources():
            ss.bell(wid, event.device, event.percent,
                    event.pitch, event.duration, event.bell_class, event.bell_id, event.name)

    def _bell_signaled(self, wm, event) -> None:
        log("bell signaled on window %#x", event.window)
        if not self.bell:
            return
        wid = 0
        rxid = get_root_xid()
        if event.window != rxid and event.window_model is not None:
            wid = self._window_to_id.get(event.window_model, 0)
        log("_bell_signaled(%s,%r) wid=%s", wm, event, wid)
        for ss in self.window_sources():
            ss.bell(wid, event.device, event.percent,
                    event.pitch, event.duration, event.bell_class, event.bell_id, event.name)

    def init_packet_handlers(self) -> None:
        if self.bell:
            self.add_packets("bell-set", main_thread=True)
            self.add_legacy_alias("set-bell", "bell-set")
