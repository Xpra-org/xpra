# -*- coding: utf-8 -*-
# This file is part of Xpra.
# Copyright (C) 2010-2018 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
from time import sleep

from xpra.log import Logger
log = Logger("network")
bandwidthlog = Logger("bandwidth")

from xpra.server.mixins.stub_server_mixin import StubServerMixin

from xpra.simple_stats import std_unit
from xpra.os_util import livefds, POSIX
from xpra.util import envbool, envint, detect_leaks


DETECT_MEMLEAKS = envbool("XPRA_DETECT_MEMLEAKS", False)
DETECT_FDLEAKS = envbool("XPRA_DETECT_FDLEAKS", False)

AUTO_BANDWIDTH_PCT = envint("XPRA_AUTO_BANDWIDTH_PCT", 80)
assert AUTO_BANDWIDTH_PCT>1 and AUTO_BANDWIDTH_PCT<=100, "invalid value for XPRA_AUTO_BANDWIDTH_PCT: %i" % AUTO_BANDWIDTH_PCT


"""
Mixin for adding client / network state monitoring functions:
- ping and echo
- bandwidth management
- leak detection (file descriptors, memory)
"""
class NetworkStateServer(StubServerMixin):

    def __init__(self):
        self.pings = False

    def init(self, opts):
        self.pings = opts.pings

    def setup(self, _opts):
        self.init_leak_detection()
        if self.pings>0:
            self.timeout_add(1000*self.pings, self.send_ping)

    def threaded_setup(self):
        self.init_memcheck()


    def get_info(self, _source=None):
        return {
            "pings"             : self.pings,
            "bandwidth-limit"   : self.bandwidth_limit or 0,
            }

    def get_server_features(self, _source):
        return {
            "connection-data" : True,
            "network" : {
                "bandwidth-limit-change"       : True,
                "bandwidth-limit"              : self.bandwidth_limit or 0,
                }
            }


    def init_leak_detection(self):
        if DETECT_MEMLEAKS:
            print_leaks = detect_leaks()
            if print_leaks:
                def leak_thread():
                    while True:
                        print_leaks()
                        sleep(10)
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
            except:
                pass


    def get_client_bandwidth_limit(self, proto):
        if self.bandwidth_limit is None:
            #auto-detect:
            pinfo = proto.get_info()
            socket_speed = pinfo.get("socket", {}).get("speed")
            if socket_speed:
                #auto: use 80% of socket speed if we have it:
                v = socket_speed*AUTO_BANDWIDTH_PCT//100 or 0
            else:
                v = 0
        else:
            v = self.bandwidth_limit
        bandwidthlog("get_client_bandwidth_limit(%s)=%s", proto, v)            
        return v


    def _process_connection_data(self, proto, packet):
        ss = self._server_sources.get(proto)
        if ss:
            ss.update_connection_data(packet[1])

    def _process_bandwidth_limit(self, proto, packet):
        ss = self._server_sources.get(proto)
        if not ss:
            return
        bandwidth_limit = packet[1]
        if self.bandwidth_limit:
            bandwidth_limit = min(self.bandwidth_limit, bandwidth_limit)
        ss.bandwidth_limit = bandwidth_limit
        bandwidthlog.info("bandwidth-limit changed to %sbps for client %i", std_unit(bandwidth_limit), ss.counter)

    def send_ping(self):
        for ss in self._server_sources.values():
            ss.ping()
        return True

    def _process_ping_echo(self, proto, packet):
        ss = self._server_sources.get(proto)
        if ss:
            ss.process_ping_echo(packet)

    def _process_ping(self, proto, packet):
        time_to_echo = packet[1]
        ss = self._server_sources.get(proto)
        if ss:
            ss.process_ping(time_to_echo)


    def init_packet_handlers(self):
        self._authenticated_packet_handlers.update({
            "ping":                                 self._process_ping,
            "ping_echo":                            self._process_ping_echo,
            "connection-data":                      self._process_connection_data,
            "bandwidth-limit":                      self._process_bandwidth_limit,
          })
