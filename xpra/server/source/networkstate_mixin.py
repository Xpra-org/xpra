# -*- coding: utf-8 -*-
# This file is part of Xpra.
# Copyright (C) 2010-2019 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import time

from xpra.util import envbool, envint, CLIENT_PING_TIMEOUT
from xpra.os_util import monotonic_time, POSIX
from xpra.server.source.stub_source_mixin import StubSourceMixin
from xpra.log import Logger

log = Logger("network")

PING_DETAILS = envbool("XPRA_PING_DETAILS", True)
PING_TIMEOUT = envint("XPRA_PING_TIMEOUT", 60)


class NetworkStateMixin(StubSourceMixin):

    def init_state(self):
        self.last_ping_echoed_time = 0
        self.check_ping_echo_timers = {}
        self.ping_timer = None
        self.bandwidth_limit = 0

    def cleanup(self):
        self.cancel_ping_echo_timers()
        self.cancel_ping_timer()

    def get_caps(self):
        return {"ping-echo-sourceid" : True}

    def get_info(self):
        lpe = 0
        if self.last_ping_echoed_time>0:
            lpe = int(monotonic_time()*1000-self.last_ping_echoed_time)
        info = {
                "bandwidth-limit"   : {
                    "setting"       : self.bandwidth_limit or 0,
                    },
                "last-ping-echo"    : lpe,
                }
        return info

    ######################################################################
    # pings:
    def ping(self):
        self.ping_timer = None
        #NOTE: all ping time/echo time/load avg values are in milliseconds
        now_ms = int(1000*monotonic_time())
        log("sending ping to %s with time=%s", self.protocol, now_ms)
        self.send_async("ping", now_ms, int(time.time()*1000), will_have_more=False)
        timeout = PING_TIMEOUT
        self.check_ping_echo_timers[now_ms] = self.timeout_add(timeout*1000,
                                                               self.check_ping_echo_timeout, now_ms, timeout)

    def check_ping_echo_timeout(self, now_ms, timeout):
        try:
            del self.check_ping_echo_timers[now_ms]
        except KeyError:
            pass
        if self.last_ping_echoed_time<now_ms and not self.is_closed():
            self.disconnect(CLIENT_PING_TIMEOUT, "waited %s seconds without a response" % timeout)

    def cancel_ping_echo_timers(self):
        timers = self.check_ping_echo_timers.values()
        self.check_ping_echo_timers = {}
        for t in timers:
            self.source_remove(t)

    def process_ping(self, time_to_echo, sid):
        l1,l2,l3 = 0,0,0
        cl = -1
        if PING_DETAILS:
            #send back the load average:
            if POSIX:
                fl1, fl2, fl3 = os.getloadavg()
                l1,l2,l3 = int(fl1*1000), int(fl2*1000), int(fl3*1000)
            #and the last client ping latency we measured (if any):
            stats = getattr(self, "statistics", None)
            if stats and stats.client_ping_latency:
                _, cl = stats.client_ping_latency[-1]
                cl = int(1000.0*cl)
        self.send_async("ping_echo", time_to_echo, l1, l2, l3, cl, sid, will_have_more=False)
        #if the client is pinging us, ping it too:
        if not self.ping_timer:
            self.ping_timer = self.timeout_add(500, self.ping)

    def cancel_ping_timer(self):
        pt = self.ping_timer
        if pt:
            self.ping_timer = None
            self.source_remove(pt)

    def process_ping_echo(self, packet):
        echoedtime, l1, l2, l3, server_ping_latency = packet[1:6]
        timer = self.check_ping_echo_timers.get(echoedtime)
        if timer:
            try:
                self.source_remove(timer)
                del self.check_ping_echo_timers[echoedtime]
            except KeyError:
                pass
        self.last_ping_echoed_time = echoedtime
        client_ping_latency = monotonic_time()-echoedtime/1000.0
        stats = getattr(self, "statistics", None)
        if stats and 0<client_ping_latency<60:
            stats.client_ping_latency.append((monotonic_time(), client_ping_latency))
        self.client_load = l1, l2, l3
        if 0<=server_ping_latency<60000 and stats:
            stats.server_ping_latency.append((monotonic_time(), server_ping_latency/1000.0))
        log("ping echo client load=%s, measured server latency=%s", self.client_load, server_ping_latency)


    def update_connection_data(self, data):
        log("update_connection_data(%s)", data)
        if not isinstance(data, dict):
            raise TypeError("connection-data must be a dictionary")
        self.client_connection_data = data
