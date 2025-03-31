# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.
# pylint: disable-msg=E1101

import os
from time import sleep
from typing import Any
from collections.abc import Callable

from xpra.server.mixins.stub_server_mixin import StubServerMixin
from xpra.scripts.config import parse_with_unit
from xpra.util.stats import std_unit
from xpra.net.common import PacketType
from xpra.os_util import POSIX, gi_import
from xpra.util.io import livefds
from xpra.util.pysystem import detect_leaks
from xpra.util.objects import typedict
from xpra.util.env import envint, envbool
from xpra.log import Logger

log = Logger("network")
bandwidthlog = Logger("network", "bandwidth")
eventslog = Logger("events")

GLib = gi_import("GLib")

DETECT_MEMLEAKS = envint("XPRA_DETECT_MEMLEAKS", 0)
DETECT_FDLEAKS = envbool("XPRA_DETECT_FDLEAKS", False)

MIN_BANDWIDTH_LIMIT = envint("XPRA_MIN_BANDWIDTH_LIMIT", 1024 * 1024)
MAX_BANDWIDTH_LIMIT = envint("XPRA_MAX_BANDWIDTH_LIMIT", 10 * 1024 * 1024 * 1024)
CPUINFO = envbool("XPRA_CPUINFO", False)


class NetworkStateServer(StubServerMixin):
    """
    Mixin for adding client / network state monitoring functions:
    - ping and echo
    - bandwidth management
    - leak detection (file descriptors, memory)
    """

    def __init__(self):
        self.pings = False
        self.ping_timer: int = 0
        self.bandwidth_limit = 0
        self.bandwidth_detection = False
        self.mem_bytes = 0
        self.cpu_info: dict = {}
        self.print_memleaks: Callable | None = None
        self.fds: set[int] = set()

    def init(self, opts) -> None:
        self.pings = opts.pings
        self.bandwidth_limit = parse_with_unit("bandwidth-limit", opts.bandwidth_limit) or 0
        self.bandwidth_detection = opts.bandwidth_detection
        bandwidthlog("bandwidth-limit(%s)=%s", opts.bandwidth_limit, self.bandwidth_limit)
        self.init_cpuinfo()

    def setup(self) -> None:
        self.init_leak_detection()
        if self.pings > 0:
            self.ping_timer = GLib.timeout_add(1000 * self.pings, self.send_ping)

    def threaded_setup(self) -> None:
        self.init_memcheck()

    def cleanup(self) -> None:
        pt = self.ping_timer
        if pt:
            self.ping_timer = 0
            GLib.source_remove(pt)
        pm = self.print_memleaks
        if pm:
            pm()

    def get_info(self, _source=None) -> dict[str, Any]:
        info = {
            "pings": self.pings,
            "bandwidth-limit": self.bandwidth_limit or 0,
        }
        if POSIX:
            info["load"] = tuple(int(x * 1000) for x in os.getloadavg())
        if self.mem_bytes:
            info["total-memory"] = self.mem_bytes
        if self.cpu_info:
            info["cpuinfo"] = {k: v for k, v in self.cpu_info.items() if k != "python_version"}
        return info

    def get_server_features(self, _source) -> dict[str, Any]:
        return {
            "network": {
                "bandwidth-limit": self.bandwidth_limit or 0,
            }
        }

    def init_leak_detection(self) -> None:
        if DETECT_MEMLEAKS:
            pm = detect_leaks()
            self.print_memleaks = pm
            if bool(self.print_memleaks):
                def leak_thread():
                    while not self._closing:
                        pm()
                        sleep(DETECT_MEMLEAKS)

                from xpra.util.thread import start_thread  # pylint: disable=import-outside-toplevel
                start_thread(leak_thread, "leak thread", daemon=True)
        if DETECT_FDLEAKS:
            self.fds = livefds()

            def print_fds():
                fds = livefds()
                newfds = fds - self.fds
                self.fds = fds
                log.info("print_fds() new fds=%s (total=%s)", newfds, len(fds))
                return True

            GLib.timeout_add(10, print_fds)

    def init_memcheck(self) -> None:
        # verify we have enough memory:
        if POSIX and self.mem_bytes == 0:
            try:
                self.mem_bytes = os.sysconf('SC_PAGE_SIZE') * os.sysconf('SC_PHYS_PAGES')  # e.g. 4015976448
                LOW_MEM_LIMIT = 1024 * 1024 * 1024
                if self.mem_bytes <= LOW_MEM_LIMIT:
                    log.warn("Warning: only %iMB total system memory available", self.mem_bytes // (1024 ** 2))
                    log.warn(" this may not be enough to run a server")
                else:
                    log.info("%.1fGB of system memory", self.mem_bytes / (1024.0 ** 3))
            except Exception:
                pass

    def init_cpuinfo(self) -> None:
        if not CPUINFO:
            return
        # this crashes if not run from the UI thread!
        try:
            from cpuinfo import get_cpu_info
        except ImportError as e:
            log("no cpuinfo: %s", e)
            return
        self.cpu_info = get_cpu_info()
        if self.cpu_info:
            c = typedict(self.cpu_info)
            count = c.intget("count", 0)
            brand = c.strget("brand")
            if count > 0 and brand:
                log.info("%ix %s", count, brand)

    def _process_connection_data(self, proto, packet: PacketType) -> None:
        ss = self.get_server_source(proto)
        if ss:
            ss.update_connection_data(packet[1])

    def _process_bandwidth_limit(self, proto, packet: PacketType) -> None:
        log("_process_bandwidth_limit(%s, %s)", proto, packet)
        ss = self.get_server_source(proto)
        if not ss:
            return
        bandwidth_limit = packet[1]
        if not isinstance(bandwidth_limit, int):
            raise TypeError("bandwidth-limit must be an integer, not %s" % type(bandwidth_limit))
        if (self.bandwidth_limit and bandwidth_limit >= self.bandwidth_limit) or bandwidth_limit <= 0:
            bandwidth_limit = self.bandwidth_limit or 0
        if ss.bandwidth_limit == bandwidth_limit:
            # unchanged
            log("bandwidth limit unchanged: %s", std_unit(bandwidth_limit))
            return
        if bandwidth_limit < MIN_BANDWIDTH_LIMIT:
            log.warn("Warning: bandwidth limit requested is too low (%s)", std_unit(bandwidth_limit))
            bandwidth_limit = MIN_BANDWIDTH_LIMIT
        if bandwidth_limit >= MAX_BANDWIDTH_LIMIT:
            log("bandwidth limit over maximum, using no-limit instead")
            bandwidth_limit = 0
        ss.bandwidth_limit = bandwidth_limit
        # we can't assume to have a full ClientConnection object:
        client_id = getattr(ss, "counter", "")
        if bandwidth_limit == 0:
            bandwidthlog.info("bandwidth-limit restrictions removed for client %s", client_id)
        else:
            bandwidthlog.info("bandwidth-limit changed to %sbps for client %s", std_unit(bandwidth_limit), client_id)

    def send_ping(self) -> bool:
        from xpra.server.source.networkstate import NetworkStateMixin
        for ss in self._server_sources.values():
            if ss.suspended or ss.is_closed() or not ss.startup_completed:
                continue
            if isinstance(ss, NetworkStateMixin):
                ss.ping()
        return True

    def _process_ping_echo(self, proto, packet: PacketType) -> None:
        ss = self.get_server_source(proto)
        if ss:
            ss.process_ping_echo(packet)

    def _process_ping(self, proto, packet: PacketType) -> None:
        time_to_echo = packet[1]
        sid = ""
        if len(packet) >= 4:
            sid = packet[3]
        ss = self.get_server_source(proto)
        if ss:
            ss.process_ping(time_to_echo, sid)

    def _process_suspend(self, proto, packet: PacketType) -> None:
        ss = self.get_server_source(proto)
        eventslog("suspend(%s) source=%s", packet[1:], ss)
        if ss:
            ss.suspend()

    def _process_resume(self, proto, packet: PacketType) -> None:
        ss = self.get_server_source(proto)
        eventslog("resume(%s) source=%s", packet[1:], ss)
        if ss:
            ss.resume()

    def init_packet_handlers(self) -> None:
        self.add_packets(
            "ping", "ping_echo",
            "connection-data", "bandwidth-limit",
        )
        self.add_packets(
            "suspend", "resume",
            main_thread=True,
        )
