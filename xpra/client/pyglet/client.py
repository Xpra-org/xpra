# This file is part of Xpra.
# Copyright (C) 2025 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys
import uuid
import signal
from typing import Any
from time import monotonic
from collections.abc import Callable

from pyglet import app, clock

from xpra import __version__
from xpra.common import noop
from xpra.exit_codes import ExitValue
from xpra.net.protocol.factory import get_client_protocol_class
from xpra.net.common import PacketType
from xpra.log import Logger

log = Logger("client")
netlog = Logger("client", "network")


class scheduled:
    def __init__(self, fn: Callable, args, kwargs):
        self.function = fn
        self.args = args
        self.kwargs = kwargs

    def run(self, elapsed: float):
        try:
            log(f"scheduled.run({elapsed}) calling {self.function}{self.args}{self.kwargs}")
            ret = self.function(*self.args, **self.kwargs)
        except Exception:
            log(f"scheduled error calling {self.function}{self.args}{self.kwargs}", exc_info=True)
            ret = False
        if not ret:
            clock.unschedule(self.run)


class PygletScheduler:

    def __init__(self):
        self.scheduled = []

    def idle_add(self, fn: Callable, *args, **kwargs):
        return self.timeout_add(0, fn, *args, **kwargs)

    def timeout_add(self, delay: int, fn: Callable, *args, **kwargs):
        # interval is in seconds:
        interval = delay / 1000
        instance = scheduled(fn, args, kwargs)
        self.scheduled.append(instance)
        log(f"pyglet_clock_scheduler: {instance} in {interval} seconds")
        clock.schedule_interval(instance.run, interval)


class XpraPygletClient:

    def __init__(self):
        self.windows: dict[int, Any] = {}
        self.hello = {}
        self.focused = 0
        self._ordinary_packets = []
        self.protocol = None
        self.have_more = noop

    def show_progress(self, pct: int, msg) -> None:
        log(f"show_progress({pct}, {msg})")

    def run(self) -> int:
        app.run()
        return 0

    def quit(self, exit_code: ExitValue):
        sys.exit(int(exit_code))

    def init(self, opts) -> None:
        """ we don't handle any options yet! """

    def init_ui(self, opts) -> None:
        """ we don't handle any options yet! """

    def cleanup(self) -> None:
        """ client classes must define this method """

    def make_protocol(self, conn):
        protocol_class = get_client_protocol_class(conn.socktype)
        protocol = protocol_class(conn, self.process_packet, self.next_packet, scheduler=PygletScheduler())
        log(f"setup_connection({conn}) {protocol=}")
        protocol.enable_default_encoder()
        protocol.enable_default_compressor()
        self._protocol = protocol
        self.have_more = protocol.source_has_more
        clock.schedule_once(self.send_hello, 1)
        return protocol

    def send_hello(self, elapsed) -> None:
        log(f"send_hello({elapsed})")
        hello = {
            "version": __version__,
            "client_type": "pyglet",
            "rencodeplus": True,
            "session-id": uuid.uuid4().hex,
            "windows": True,
            "keyboard": True,
            "mouse": True,
            "encodings": ("png", "jpg", "webp"),    # "rgb32", "rgb24"
            "network-state": False,  # tell older server that we don't have "ping"
        }
        self.send("hello", hello)

    def send(self, packet_type: str, *args) -> None:
        packet = (packet_type, *args)
        # data = dumps(packet)
        # header = pack_header(FLAGS_RENCODEPLUS, 0, 0, len(data))
        # bin_packet = header+data
        netlog(f"sent {packet_type!r}: {packet!r}")
        self._ordinary_packets.append(packet)
        self.have_more()

    def next_packet(self) -> tuple[PacketType, bool, bool]:
        packet = self._ordinary_packets.pop(0)
        return packet, True, bool(self._ordinary_packets)

    def process_packet(self, _protocol, packet: PacketType) -> None:
        packet_type_fn_name = str(packet[0]).replace("-", "_")
        meth = getattr(self, f"_process_{packet_type_fn_name}", None)
        if not meth:
            netlog.warn(f"Warning: missing handler for {packet[0]!r}")
            netlog("packet=%r", packet)
            return

        def call_handler(_elapsed) -> None:
            meth(packet)
        clock.schedule_once(call_handler, 0)

    def _process_hello(self, packet: PacketType) -> None:
        self.hello = packet[1]
        netlog.info("got hello from %s server" % self.hello.get("version", ""))

    def _process_setting_change(self, packet: PacketType) -> None:
        setting = packet[1]
        netlog.info(f"ignoring setting-change for {setting!r}")

    def _process_startup_complete(self, _packet: PacketType) -> None:
        netlog.info("client is connected")

    def _process_encodings(self, packet: PacketType) -> None:
        log(f"server encodings: {packet[1]}")

    def _process_new_window(self, packet: PacketType) -> None:
        self.new_window(packet)

    def _process_new_override_redirect(self, packet: PacketType) -> None:
        self.new_window(packet, True)

    def new_window(self, packet: PacketType, is_or=False) -> None:
        from xpra.client.pyglet.window import ClientWindow
        wid, x, y, w, h = (int(item) for item in packet[1:6])
        metadata = packet[6]
        if is_or:
            metadata["override-redirect"] = is_or
        window = ClientWindow(self, wid, x, y, w, h, metadata)
        self.windows[wid] = window
        window.show()

    def _process_lost_window(self, packet: PacketType) -> None:
        wid = int(packet[1])
        window = self.windows.get(wid)
        if window:
            window.close()
            del self.windows[wid]

    def _process_raise_window(self, packet: PacketType) -> None:
        wid = int(packet[1])
        window = self.windows.get(wid)
        if window:
            window.raise_()

    def _process_draw(self, packet: PacketType) -> None:
        wid, x, y, width, height, coding, data, packet_sequence, rowstride = packet[1:10]
        window = self.windows.get(wid)
        now = monotonic()
        if window:
            message = ""
            window.draw(x, y, width, height, coding, data, rowstride)
            decode_time = int(1000 * (monotonic() - now))
        else:
            message = f"Warning: window {wid} not found"
            log.warn(message)
            decode_time = -1
        self.send("damage-sequence", packet_sequence, wid, width, height, decode_time, message)

    def _process_window_metadata(self, packet: PacketType) -> None:
        wid = packet[1]
        metadata = packet[2]
        log.info(f"window {wid}: {metadata}")

    def update_focus(self, wid=0) -> None:
        if self.focused == wid:
            return
        self.focused = wid

        def recheck_focus(_elapsed) -> None:
            if self.focused == wid:
                self.send("focus", wid, ())
        clock.schedule_once(recheck_focus, 0.01)


def make_client() -> XpraPygletClient:
    signal.signal(signal.SIGINT, signal.SIG_DFL)
    client = XpraPygletClient()
    return client


def run_client(host: str, port: int) -> int:
    client = make_client()
    client.connect(host, port)
    return client.run()
