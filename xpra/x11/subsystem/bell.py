# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from typing import Any

from xpra.net.common import Packet
from xpra.server.subsystem.stub import StubSubsystem
from xpra.x11.bindings.core import get_root_xid
from xpra.x11.dispatch import add_event_receiver
from xpra.x11.common import X11Event
from xpra.log import Logger

log = Logger("bell")


class BellServer(StubSubsystem):
    """
    Servers that forward bell events.

    The `x11-xkb-event` signal that drives bell forwarding is declared on
    each X11 server class's `__gsignals__` (seamless, desktop, monitor,
    X11 shadow). It is *not* declared on this subsystem because the X11
    dispatch (`xpra.x11.dispatch._maybe_send_event`) calls `signal_list_names`
    on each receiver and only accepts a GObject — `BellServer` is a plain
    Python object. Subsystems consume the signal via `self.server.connect`.
    """
    PREFIX = "bell"
    toggle_features = ("bell",)

    def __init__(self, server=None):
        StubSubsystem.__init__(self, server)
        self.bell = False

    def init(self, opts) -> None:
        self.bell = opts.bell
        log(f"bell={opts.bell}")

    def get_caps(self, source) -> dict[str, Any]:
        # Note: don't just call self.get_info() to get rid of linter warnings,
        # this is not safe as it will call it on the subclass!
        return {
            "bell": self.bell,
        }

    def get_info(self, _proto) -> dict[str, Any]:
        return {
            "bell": self.bell,
        }

    def setup(self) -> None:
        if not self.bell:
            return
        try:
            from xpra.x11.bindings.keyboard import X11KeyboardBindings
            X11Keyboard = X11KeyboardBindings()
        except ImportError as e:
            log.error("Error: unable to listen for bell events:")
            log.estr(e)
            self.bell = False
        else:
            from xpra.x11.error import xlog
            with xlog:
                X11Keyboard.selectBellNotification(True)
                # The X11 dispatch (`x11.dispatch._maybe_send_event`) calls
                # `GObject.signal_list_names(handler)` on each receiver and
                # requires a GObject type. Register the server (which IS
                # GObject-registered with `x11-xkb-event` in its `__gsignals__`)
                # and connect our handler.
                rxid = get_root_xid()
                add_event_receiver(rxid, self.server)
                self.server.connect("x11-xkb-event", self._on_x11_xkb_event)

    def _on_x11_xkb_event(self, _emitter, event: X11Event) -> None:
        self.do_x11_xkb_event(event)

    def _process_bell_set(self, proto, packet: Packet) -> None:
        assert self.bell, "cannot toggle send_bell: the feature is disabled"
        if ss := self.get_server_source(proto):
            ss.window_bell = packet.get_bool(1)

    def do_x11_xkb_event(self, event: X11Event) -> None:
        log("server do_x11_xkb_event(%r) bell=%s", event, self.bell)
        if not self.bell:
            return
        # X11: XKBNotify
        if event.subtype != "bell":
            log.error(f"Error: unknown event subtype: {event.subtype!r}")
            log.error(f" {event=}")
            return
        # bell events on our windows will come through the bell signal,
        # this method is a catch-all for events on windows we don't manage,
        # so we use wid=0 for that:
        wid = 0
        for ss in self.server.window_sources():
            ss.bell(wid, event.device, event.percent,
                    event.pitch, event.duration, event.bell_class, event.bell_id, event.name)

    def _bell_signaled(self, wm, event) -> None:
        log("bell signaled on window %#x", event.window)
        if not self.bell:
            return
        wid = 0
        rxid = get_root_xid()
        if event.window != rxid and event.window_model is not None:
            if window_manager := self.get_subsystem("window"):
                wid = max(0, window_manager.get_wid(event.window_model))
        log("_bell_signaled(%s,%r) wid=%#x", wm, event, wid)
        for ss in self.server.window_sources():
            ss.bell(wid, event.device, event.percent,
                    event.pitch, event.duration, event.bell_class, event.bell_id, event.name)

    def init_packet_handlers(self) -> None:
        if self.bell:
            self.add_packets("bell-set", main_thread=True)
            self.add_legacy_alias("set-bell", "bell-set")
