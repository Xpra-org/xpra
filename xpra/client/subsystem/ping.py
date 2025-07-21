# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.
# pylint: disable-msg=E1101

import os
from time import monotonic
from collections import deque
from typing import Any
from collections.abc import Sequence, Iterable

from xpra.os_util import POSIX, gi_import
from xpra.util.env import envint, envbool
from xpra.exit_codes import ExitCode
from xpra.net.common import Packet
from xpra.common import BACKWARDS_COMPATIBLE
from xpra.client.base.stub import StubClientMixin
from xpra.log import Logger
from xpra.util.objects import typedict

GLib = gi_import("GLib")

log = Logger("network", "ping")

FAKE_BROKEN_CONNECTION: int = envint("XPRA_FAKE_BROKEN_CONNECTION")
PING_TIMEOUT: int = envint("XPRA_PING_TIMEOUT", 60)
MIN_PING_TIMEOUT: int = envint("XPRA_MIN_PING_TIMEOUT", 2)
MAX_PING_TIMEOUT: int = envint("XPRA_MAX_PING_TIMEOUT", 10)
SWALLOW_PINGS: bool = envbool("XPRA_SWALLOW_PINGS", False)


class PingClient(StubClientMixin):
    """
    Ping handling
    """

    PACKET_TYPES = ("ping", "ping_echo")

    def __init__(self):
        self.pings: bool = False
        self.server_ping_latency: deque[tuple[float, float]] = deque(maxlen=1000)
        self.server_load = (0, 0, 0)
        self.client_ping_latency: deque[tuple[float, float]] = deque(maxlen=1000)
        self._server_ok: bool = True
        self.last_ping_echoed_time = 0
        self.ping_timer: int = 0
        self.ping_echo_timers: dict[int, int] = {}
        self.ping_echo_timeout_timer = 0

    def init(self, opts) -> None:
        self.pings = opts.pings

    def cleanup(self) -> None:
        self.cancel_ping_timer()
        self.cancel_ping_echo_timers()
        self.cancel_ping_echo_timeout_timer()

    def get_info(self) -> dict[str, Any]:
        return {
            "network": {
                "ping": self.pings,
                "server-ok": self._server_ok,
            }
        }

    def get_caps(self) -> dict[str, Any]:
        caps: dict[str, Any] = {
            "ping": True,
        }
        if BACKWARDS_COMPATIBLE:
            caps.update({
                "network-state": True,
                "ping-echo-sourceid": True,
            })
        return caps

    def startup_complete(self) -> None:
        self.start_sending_pings()

    def server_ok(self) -> bool:
        return self._server_ok

    def suspend(self) -> None:
        self.cancel_ping_timer()
        self.cancel_ping_echo_timers()

    def resume(self) -> None:
        self.start_sending_pings()

    def parse_server_capabilities(self, c: typedict) -> bool:
        if self.pings:
            self.pings = c.boolget("ping", BACKWARDS_COMPATIBLE)
        return True

    def start_sending_pings(self) -> None:
        log("start_sending_pings() pings=%s, ping_timer=%s", self.pings, self.ping_timer)
        if self.pings > 0 and not self.ping_timer:
            self.send_ping()
            self.ping_timer = GLib.timeout_add(1000 * self.pings, self.send_ping)

    def cancel_ping_timer(self) -> None:
        pt = self.ping_timer
        if pt:
            self.ping_timer = 0
            GLib.source_remove(pt)

    def cancel_ping_echo_timers(self) -> None:
        pet: Iterable[int] = tuple(self.ping_echo_timers.values())
        self.ping_echo_timers = {}
        for t in pet:
            GLib.source_remove(t)

    def check_server_echo(self, ping_sent_time) -> bool:
        self.ping_echo_timers.pop(ping_sent_time, None)
        if self._protocol is None:
            # no longer connected!
            return False
        last = self._server_ok
        self._server_ok = self.last_ping_echoed_time >= ping_sent_time
        if FAKE_BROKEN_CONNECTION > 0:
            fakeit = (int(monotonic()) % FAKE_BROKEN_CONNECTION) <= FAKE_BROKEN_CONNECTION // 2
            self._server_ok = self._server_ok and fakeit
        if not self._server_ok:
            if not self.ping_echo_timeout_timer:
                self.ping_echo_timeout_timer = GLib.timeout_add(PING_TIMEOUT * 1000,
                                                                self.check_echo_timeout, ping_sent_time)
        else:
            self.cancel_ping_echo_timeout_timer()
        log("check_server_echo(%s) last=%s, server_ok=%s (last_ping_echoed_time=%s)",
            ping_sent_time, last, self._server_ok, self.last_ping_echoed_time)
        if last != self._server_ok:
            self.server_connection_state_change()
        return False

    def cancel_ping_echo_timeout_timer(self) -> None:
        pett = self.ping_echo_timeout_timer
        if pett:
            self.ping_echo_timeout_timer = 0
            GLib.source_remove(pett)

    def server_connection_state_change(self) -> None:
        log("server_connection_state_change() ok=%s", self._server_ok)

    def check_echo_timeout(self, ping_time) -> None:
        self.ping_echo_timeout_timer = 0
        expired = self.last_ping_echoed_time < ping_time
        log(f"check_echo_timeout({ping_time}) last={self.last_ping_echoed_time}, {expired=}")
        if expired:
            # no point trying to use disconnect_and_quit() to tell the server here..
            self.warn_and_quit(ExitCode.CONNECTION_LOST,
                               "server ping timeout - waited %s seconds without a response" % PING_TIMEOUT)

    def send_ping(self) -> bool:
        p = self._protocol
        protocol_type = getattr(p, "TYPE", "undefined")
        if protocol_type not in ("xpra", "websocket"):
            log(f"not sending ping for {protocol_type} connection")
            self.ping_timer = 0
            return False
        now_ms = int(1000.0 * monotonic())
        self.send("ping", now_ms)
        wait = 1000 * MIN_PING_TIMEOUT
        aspl = tuple(self.server_ping_latency)
        if aspl:
            spl: Sequence[float] = tuple(x[1] for x in aspl)
            avg = sum(spl) / len(spl)
            wait = max(1000 * MIN_PING_TIMEOUT, min(1000 * MAX_PING_TIMEOUT, round(1000 + avg * 2000)))
            log("send_ping() timestamp=%s, average server latency=%ims, using max wait %ims",
                now_ms, round(1000 * avg), wait)
        t = GLib.timeout_add(wait, self.check_server_echo, now_ms)
        log(f"send_ping() time={now_ms}, timer={t}")
        self.ping_echo_timers[now_ms] = t
        return True

    def _process_ping_echo(self, packet: Packet) -> None:
        echoedtime = packet.get_u64(1)
        l1 = packet.get_u64(2)
        l2 = packet.get_u64(3)
        l3 = packet.get_u64(4)
        cl = packet.get_i64(5)
        self.last_ping_echoed_time = echoedtime
        self.check_server_echo(0)
        server_ping_latency = monotonic() - echoedtime / 1000.0
        self.server_ping_latency.append((monotonic(), server_ping_latency))
        self.server_load = l1, l2, l3
        if cl >= 0:
            self.client_ping_latency.append((monotonic(), cl / 1000.0))
        log("ping echo server load=%s, measured client latency=%sms", self.server_load, cl)

    def _process_ping(self, packet: Packet) -> None:
        echotime = packet.get_u64(1)
        l1, l2, l3 = 0, 0, 0
        sid = ""
        if len(packet) >= 4:
            sid = packet.get_str(3)
        if POSIX:
            try:
                (fl1, fl2, fl3) = os.getloadavg()
                l1, l2, l3 = int(fl1 * 1000), int(fl2 * 1000), int(fl3 * 1000)
            except (OSError, AttributeError):
                pass
        try:
            sl = self.server_ping_latency[-1][1]
        except IndexError:
            sl = -1
        if SWALLOW_PINGS > 0:
            log("swallowed ping!")
            return
        log(f"got ping, sending echo time={echotime} for {sid=}")
        self.send("ping_echo", echotime, l1, l2, l3, int(1000.0 * sl), sid)

    ######################################################################
    # packets:
    def init_authenticated_packet_handlers(self) -> None:
        self.add_packets(*PingClient.PACKET_TYPES)
