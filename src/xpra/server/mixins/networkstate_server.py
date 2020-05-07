# -*- coding: utf-8 -*-
# This file is part of Xpra.
# Copyright (C) 2010-2020 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.
#pylint: disable-msg=E1101

import os
from time import sleep

from xpra.server.mixins.stub_server_mixin import StubServerMixin
from xpra.scripts.config import parse_with_unit
from xpra.simple_stats import std_unit
from xpra.os_util import livefds, POSIX
from xpra.util import envbool, envint, detect_leaks, typedict
from xpra.log import Logger

log = Logger("network")
bandwidthlog = Logger("bandwidth")

DETECT_MEMLEAKS = envint("XPRA_DETECT_MEMLEAKS", 0)
DETECT_FDLEAKS = envbool("XPRA_DETECT_FDLEAKS", False)

MIN_BANDWIDTH_LIMIT = envint("XPRA_MIN_BANDWIDTH_LIMIT", 1024*1024)
MAX_BANDWIDTH_LIMIT = envint("XPRA_MAX_BANDWIDTH_LIMIT", 10*1024*1024*1024)
CPUINFO = envbool("XPRA_CPUINFO", False)

"""
Mixin for adding client / network state monitoring functions:
- ping and echo
- bandwidth management
- leak detection (file descriptors, memory)
"""
class NetworkStateServer(StubServerMixin):

    def __init__(self):
        self.pings = False
        self.ping_timer = None
        self.mem_bytes = 0
        self.cpu_info = None
        self.print_memleaks = None

    def init(self, opts):
        self.pings = opts.pings
        self.bandwidth_limit = parse_with_unit("bandwidth-limit", opts.bandwidth_limit)
        bandwidthlog("bandwidth-limit(%s)=%s", opts.bandwidth_limit, self.bandwidth_limit)
        self.init_cpuinfo()

    def setup(self):
        self.init_leak_detection()
        if self.pings>0:
            self.ping_timer = self.timeout_add(1000*self.pings, self.send_ping)

    def threaded_setup(self):
        self.init_memcheck()

    def cleanup(self):
        pt = self.ping_timer
        if pt:
            self.ping_timer = None
            self.source_remove(pt)
        pm = self.print_memleaks
        if pm:
            pm()

    def get_info(self, _source=None) -> dict:
        info = {
            "pings"             : self.pings,
            "bandwidth-limit"   : self.bandwidth_limit or 0,
            }
        if POSIX:
            info["load"] = tuple(int(x*1000) for x in os.getloadavg())
        if self.mem_bytes:
            info["total-memory"] = self.mem_bytes
        if self.cpu_info:
            info["cpuinfo"] = dict((k,v) for k,v in self.cpu_info.items() if k!="python_version")
        return info

    def get_server_features(self, _source) -> dict:
        return {
            "connection-data" : True,           #added in v2.3
            "network" : {
                "bandwidth-limit-change"       : True,  #added in v2.2
                "bandwidth-limit"              : self.bandwidth_limit or 0,
                }
            }


    def init_leak_detection(self):
        if DETECT_MEMLEAKS:
            self.print_memleaks = detect_leaks()
            if bool(self.print_memleaks):
                def leak_thread():
                    while not self._closing:
                        self.print_memleaks()
                        sleep(DETECT_MEMLEAKS)
                from xpra.make_thread import start_thread
                start_thread(leak_thread, "leak thread", daemon=True)
        if DETECT_FDLEAKS:
            self.fds = livefds()
            def print_fds():
                fds = livefds()
                newfds = fds-self.fds
                self.fds = fds
                log.info("print_fds() new fds=%s (total=%s)", newfds, len(fds))
                return True
            self.timeout_add(10, print_fds)

    def init_memcheck(self):
        #verify we have enough memory:
        if POSIX and self.mem_bytes==0:
            try:
                self.mem_bytes = os.sysconf('SC_PAGE_SIZE') * os.sysconf('SC_PHYS_PAGES')  # e.g. 4015976448
                LOW_MEM_LIMIT = 512*1024*1024
                if self.mem_bytes<=LOW_MEM_LIMIT:
                    log.warn("Warning: only %iMB total system memory available", self.mem_bytes//(1024**2))
                    log.warn(" this may not be enough to run a server")
                else:
                    log.info("%.1fGB of system memory", self.mem_bytes/(1024.0**3))
            except Exception:
                pass

    def init_cpuinfo(self):
        if not CPUINFO:
            return
        #this crashes if not run from the UI thread!
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
            if count>0 and brand:
                log.info("%ix %s", count, brand)


    def _process_connection_data(self, proto, packet):
        ss = self.get_server_source(proto)
        if ss:
            ss.update_connection_data(packet[1])

    def _process_bandwidth_limit(self, proto, packet):
        log("_process_bandwidth_limit(%s, %s)", proto, packet)
        ss = self.get_server_source(proto)
        if not ss:
            return
        bandwidth_limit = packet[1]
        if not isinstance(bandwidth_limit, int):
            raise TypeError("bandwidth-limit must be an integer, not %s" % type(bandwidth_limit))
        if (self.bandwidth_limit and bandwidth_limit>=self.bandwidth_limit) or bandwidth_limit<=0:
            bandwidth_limit = self.bandwidth_limit or 0
        if ss.bandwidth_limit==bandwidth_limit:
            #unchanged
            log("bandwidth limit unchanged: %s", std_unit(bandwidth_limit))
            return
        if bandwidth_limit<MIN_BANDWIDTH_LIMIT:
            log.warn("Warning: bandwidth limit requested is too low (%s)", std_unit(bandwidth_limit))
            bandwidth_limit = MIN_BANDWIDTH_LIMIT
        if bandwidth_limit>=MAX_BANDWIDTH_LIMIT:
            log("bandwidth limit over maximum, using no-limit instead")
            bandwidth_limit = 0
        ss.bandwidth_limit = bandwidth_limit
        #we can't assume to have a full ClientConnection object:
        client_id = getattr(ss, "counter", "")
        if bandwidth_limit==0:
            bandwidthlog.info("bandwidth-limit restrictions removed for client %s", client_id)
        else:
            bandwidthlog.info("bandwidth-limit changed to %sbps for client %s", std_unit(bandwidth_limit), client_id)

    def send_ping(self) -> bool:
        from xpra.server.source.networkstate_mixin import NetworkStateMixin
        for ss in self._server_sources.values():
            if isinstance(ss, NetworkStateMixin):
                ss.ping()
        return True

    def _process_ping_echo(self, proto, packet):
        ss = self.get_server_source(proto)
        if ss:
            ss.process_ping_echo(packet)

    def _process_ping(self, proto, packet):
        time_to_echo = packet[1]
        sid = ""
        if len(packet)>=4:
            sid = packet[3]
        ss = self.get_server_source(proto)
        if ss:
            ss.process_ping(time_to_echo, sid)


    def init_packet_handlers(self):
        self.add_packet_handlers({
            "ping":                                 self._process_ping,
            "ping_echo":                            self._process_ping_echo,
            "connection-data":                      self._process_connection_data,
            "bandwidth-limit":                      self._process_bandwidth_limit,
          }, False)
