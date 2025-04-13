# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.
# pylint: disable-msg=E1101

import os
import re
from time import monotonic
from collections import deque
from typing import Any
from collections.abc import Callable, Sequence, Iterable

from xpra.net.device_info import (
    get_NM_adapter_type, get_device_value, guess_adapter_type,
    jitter_for_adapter_type, guess_bandwidth_limit,
)
from xpra.os_util import gi_import, POSIX
from xpra.util.objects import typedict
from xpra.util.str_fn import csv, Ellipsizer
from xpra.util.env import envint, envbool
from xpra.exit_codes import ExitCode
from xpra.net.common import PacketType
from xpra.net.packet_encoding import VALID_ENCODERS
from xpra.client.base.stub_client_mixin import StubClientMixin
from xpra.scripts.config import parse_with_unit
from xpra.log import Logger

GLib = gi_import("GLib")

log = Logger("network")
bandwidthlog = Logger("network", "bandwidth")
pinglog = Logger("network", "ping")

SSH_AGENT: bool = envbool("XPRA_SSH_AGENT", True)
FAKE_BROKEN_CONNECTION: int = envint("XPRA_FAKE_BROKEN_CONNECTION")
PING_TIMEOUT: int = envint("XPRA_PING_TIMEOUT", 60)
MIN_PING_TIMEOUT: int = envint("XPRA_MIN_PING_TIMEOUT", 2)
MAX_PING_TIMEOUT: int = envint("XPRA_MAX_PING_TIMEOUT", 10)
SWALLOW_PINGS: bool = envbool("XPRA_SWALLOW_PINGS", False)
# LOG_INFO_RESPONSE = ("^window.*position", "^window.*size$")
LOG_INFO_RESPONSE: str = os.environ.get("XPRA_LOG_INFO_RESPONSE", "")
AUTO_BANDWIDTH_PCT: int = envint("XPRA_AUTO_BANDWIDTH_PCT", 80)
assert 1 < AUTO_BANDWIDTH_PCT <= 100, "invalid value for XPRA_AUTO_BANDWIDTH_PCT: %i" % AUTO_BANDWIDTH_PCT


def parse_speed(v):
    return parse_with_unit("speed", v)


class NetworkState(StubClientMixin):
    """
    Mixin for adding server / network state monitoring functions:
    - ping and echo
    - info request and response
    """

    PACKET_TYPES = ("ping", "ping_echo", "info-response")

    def __init__(self):
        self.server_start_time: float = -1
        # legacy:
        self.compression_level: int = 0

        # setting:
        self.pings: bool = False

        # bandwidth
        self.bandwidth_limit: int = 0
        self.bandwidth_detection: bool = False
        self.server_bandwidth_limit: int = 0
        self.server_session_name: str = ""

        # info requests
        self.server_last_info: dict = {}
        self.info_request_pending: bool = False

        # network state:
        self.server_packet_encoders: Sequence[str] = ()
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
        self.bandwidth_limit = parse_with_unit("bandwidth-limit", opts.bandwidth_limit) or 0
        self.bandwidth_detection = opts.bandwidth_detection
        bandwidthlog("init bandwidth_limit=%s", self.bandwidth_limit)

    def cleanup(self) -> None:
        self.cancel_ping_timer()
        self.cancel_ping_echo_timers()
        self.cancel_ping_echo_timeout_timer()

    def get_info(self) -> dict[str, Any]:
        return {
            "network": {
                "pings": self.pings,
                "bandwidth-limit": self.bandwidth_limit,
                "bandwidth-detection": self.bandwidth_detection,
                "server-ok": self._server_ok,
            }
        }

    def get_caps(self) -> dict[str, Any]:
        caps: dict[str, Any] = {
            "network-state": True,
        }
        ssh_auth_sock = os.environ.get("SSH_AUTH_SOCK")
        if SSH_AGENT and ssh_auth_sock and os.path.isabs(ssh_auth_sock):
            # ensure agent forwarding is actually requested?
            # (checking the socket type is not enough:
            # one could still bind mount the path and connect via tcp! why though?)
            # meh: if the transport doesn't have agent forwarding enabled,
            # then it won't create a server-side socket
            # and nothing will happen,
            # exposing this client-side path is no big deal
            caps["ssh-auth-sock"] = ssh_auth_sock
        # get socket speed if we have it:
        pinfo = self._protocol.get_info()
        device_info = pinfo.get("socket", {}).get("device", {})
        try:
            coptions = self._protocol._conn.options
        except AttributeError:
            coptions = {}
        log("get_caps() device_info=%s, connection options=%s", device_info, coptions)

        def device_value(attr: str, conv: Callable = str, default_value: Any = ""):
            return get_device_value(coptions, device_info, attr, conv, default_value)

        device_name = device_info.get("name", "")
        log("get_caps() found device name=%s", device_name)
        default_adapter_type = guess_adapter_type(get_NM_adapter_type(device_name) or device_name)
        adapter_type = device_value("adapter-type", str, default_adapter_type)
        log("get_caps() found adapter-type=%s", adapter_type)
        socket_speed = device_value("speed", parse_speed, 0)
        log("get_caps() found socket_speed=%s", socket_speed)
        jitter = device_value("jitter", int, jitter_for_adapter_type(adapter_type))
        log("get_caps() found jitter=%s", jitter)

        connection_data = {}
        if adapter_type:
            connection_data["adapter-type"] = adapter_type
        if jitter >= 0:
            connection_data["jitter"] = jitter
        if socket_speed:
            connection_data["speed"] = socket_speed
        log("get_caps() connection-data=%s", connection_data)
        caps["connection-data"] = connection_data

        bandwidth_limit = self.bandwidth_limit
        bandwidthlog("bandwidth-limit setting=%s, socket-speed=%s", self.bandwidth_limit, socket_speed)
        if bandwidth_limit is None:
            if socket_speed:
                # auto: use 80% of socket speed if we have it:
                bandwidth_limit = socket_speed * AUTO_BANDWIDTH_PCT // 100 or 0
            else:
                bandwidth_limit = guess_bandwidth_limit(adapter_type)
        bandwidthlog("bandwidth-limit capability=%s", bandwidth_limit)
        if bandwidth_limit > 0:
            caps["bandwidth-limit"] = bandwidth_limit
        caps["bandwidth-detection"] = self.bandwidth_detection
        caps["ping-echo-sourceid"] = True
        return caps

    def parse_server_capabilities(self, c: typedict) -> bool:
        # make sure the server doesn't provide a start time in the future:
        import time
        self.server_start_time = min(time.time(), c.intget("start_time", -1))
        self.server_bandwidth_limit = c.intget("network.bandwidth-limit")
        bandwidthlog(f"{self.server_bandwidth_limit=}")
        self.server_packet_encoders = tuple(x for x in VALID_ENCODERS if c.boolget(x, False))
        return True

    def process_ui_capabilities(self, caps: typedict) -> None:
        self.start_sending_pings()

    def suspend(self) -> None:
        self.cancel_ping_timer()
        self.cancel_ping_echo_timers()

    def resume(self) -> None:
        self.start_sending_pings()

    # timers:

    def start_sending_pings(self):
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

    ######################################################################
    # info:
    def _process_info_response(self, packet: PacketType) -> None:
        self.info_request_pending = False
        self.server_last_info = packet[1]
        log("info-response: %s", Ellipsizer(self.server_last_info))
        if LOG_INFO_RESPONSE:
            items = LOG_INFO_RESPONSE.split(",")
            logres = [re.compile(v) for v in items]
            log.info("info-response debug for %s:", csv("'%s'" % x for x in items))
            for k in sorted(self.server_last_info.keys()):
                if LOG_INFO_RESPONSE == "all" or any(lr.match(k) for lr in logres):
                    log.info(" %s=%s", k, self.server_last_info[k])

    def send_info_request(self, *categories: str) -> None:
        if not self.info_request_pending:
            self.info_request_pending = True
            window_ids = ()  # no longer used or supported by servers
            self.send("info-request", [self.uuid], window_ids, categories)

    ######################################################################
    # network and status:
    def server_ok(self) -> bool:
        return self._server_ok

    def check_server_echo(self, ping_sent_time):
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
        pinglog(f"check_echo_timeout({ping_time}) last={self.last_ping_echoed_time}, {expired=}")
        if expired:
            # no point trying to use disconnect_and_quit() to tell the server here..
            self.warn_and_quit(ExitCode.CONNECTION_LOST,
                               "server ping timeout - waited %s seconds without a response" % PING_TIMEOUT)

    def send_ping(self) -> bool:
        p = self._protocol
        protocol_type = getattr(p, "TYPE", "undefined")
        if protocol_type not in ("xpra", "websocket"):
            pinglog(f"not sending ping for {protocol_type} connection")
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
            pinglog("send_ping() timestamp=%s, average server latency=%ims, using max wait %ims",
                    now_ms, round(1000 * avg), wait)
        t = GLib.timeout_add(wait, self.check_server_echo, now_ms)
        pinglog(f"send_ping() time={now_ms}, timer={t}")
        self.ping_echo_timers[now_ms] = t
        return True

    def _process_ping_echo(self, packet: PacketType) -> None:
        echoedtime, l1, l2, l3, cl = packet[1:6]
        self.last_ping_echoed_time = echoedtime
        self.check_server_echo(0)
        server_ping_latency = monotonic() - echoedtime / 1000.0
        self.server_ping_latency.append((monotonic(), server_ping_latency))
        self.server_load = l1, l2, l3
        if cl >= 0:
            self.client_ping_latency.append((monotonic(), cl / 1000.0))
        pinglog("ping echo server load=%s, measured client latency=%sms", self.server_load, cl)

    def _process_ping(self, packet: PacketType) -> None:
        echotime = packet[1]
        l1, l2, l3 = 0, 0, 0
        sid = ""
        if len(packet) >= 4:
            sid = packet[3]
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
            pinglog("swallowed ping!")
            return
        pinglog(f"got ping, sending echo time={echotime} for {sid=}")
        self.send("ping_echo", echotime, l1, l2, l3, int(1000.0 * sl), sid)

    ######################################################################
    def send_bandwidth_limit(self) -> None:
        bandwidthlog("send_bandwidth_limit() bandwidth-limit=%i", self.bandwidth_limit)
        self.send("bandwidth-limit", self.bandwidth_limit)

    ######################################################################
    # packets:
    def init_authenticated_packet_handlers(self) -> None:
        self.add_packets(*NetworkState.PACKET_TYPES)
