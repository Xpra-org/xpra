# This file is part of Xpra.
# Copyright (C) 2010-2018 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import re
from collections import deque

from xpra.log import Logger
log = Logger("network")
bandwidthlog = Logger("bandwidth")

from xpra.os_util import monotonic_time, get_user_uuid, POSIX
from xpra.util import envint, csv
from xpra.exit_codes import EXIT_TIMEOUT
from xpra.client.mixins.stub_client_mixin import StubClientMixin
from xpra.scripts.config import parse_with_unit


FAKE_BROKEN_CONNECTION = envint("XPRA_FAKE_BROKEN_CONNECTION")
PING_TIMEOUT = envint("XPRA_PING_TIMEOUT", 60)
#LOG_INFO_RESPONSE = ("^window.*position", "^window.*size$")
LOG_INFO_RESPONSE = os.environ.get("XPRA_LOG_INFO_RESPONSE", "")
AUTO_BANDWIDTH_PCT = envint("XPRA_AUTO_BANDWIDTH_PCT", 80)
assert AUTO_BANDWIDTH_PCT>1 and AUTO_BANDWIDTH_PCT<=100, "invalid value for XPRA_AUTO_BANDWIDTH_PCT: %i" % AUTO_BANDWIDTH_PCT


"""
Mixin for adding server / network state monitoring functions:
- ping and echo
- info request and response
"""
class NetworkState(StubClientMixin):

    def __init__(self):
        StubClientMixin.__init__(self)
        self.uuid = get_user_uuid()

        self.server_start_time = -1

        #setting:
        self.pings = False

        #bandwidth
        self.bandwidth_limit = 0
        self.server_bandwidth_limit_change = False
        self.server_bandwidth_limit = 0
        self.server_session_name = None

        #info requests
        self.server_last_info = None
        self.info_request_pending = False

        #network state:
        self.server_ping_latency = deque(maxlen=1000)
        self.server_load = None
        self.client_ping_latency = deque(maxlen=1000)
        self._server_ok = True
        self.last_ping_echoed_time = 0
        self.ping_timer = None
        self.ping_echo_timers = {}
        self.ping_echo_timeout_timer = None


    def init(self, opts):
        self.pings = opts.pings
        self.bandwidth_limit = parse_with_unit("bandwidth-limit", opts.bandwidth_limit)
        bandwidthlog("init bandwidth_limit=%s", self.bandwidth_limit)


    def cleanup(self):
        self.cancel_ping_timer()
        self.cancel_ping_echo_timers()
        self.cancel_ping_echo_timeout_timer()


    def get_caps(self):
        caps = {"info-namespace" : True}
        #get socket speed if we have it:
        pinfo = self._protocol.get_info()
        device_info = pinfo.get("socket", {}).get("device", {})
        connection_data = {}
        socket_speed = device_info.get("speed")
        if socket_speed:
            connection_data["speed"] = socket_speed
        adapter_type = device_info.get("adapter-type")
        if adapter_type:
            at = adapter_type.lower()
            if any(at.find(x)>=0 for x in ("ethernet", "local", "fiber", "1394")):
                jitter = 0
            elif at.find("wan")>=0:
                jitter = 20
            elif at.find("wireless")>=0 or at.find("wifi")>=0 or at.find("80211")>=0:
                jitter = 1000
            if jitter is not None:
                connection_data["jitter"] = jitter
        caps["connection-data"] = connection_data
        bandwidth_limit = self.bandwidth_limit
        bandwidthlog("bandwidth-limit setting=%s, socket-speed=%s", self.bandwidth_limit, socket_speed)
        if bandwidth_limit is None:
            if socket_speed:
                #auto: use 80% of socket speed if we have it:
                bandwidth_limit = socket_speed*AUTO_BANDWIDTH_PCT//100 or 0
            else:
                bandwidth_limit = 0
        bandwidthlog("bandwidth-limit capability=%s", bandwidth_limit)
        if bandwidth_limit>0:
            caps["bandwidth-limit"] = bandwidth_limit
        return caps

    def parse_server_capabilities(self):
        c = self.server_capabilities
        self.server_start_time = c.intget("start_time", -1)
        self.server_bandwidth_limit_change = c.boolget("network.bandwidth-limit-change")
        self.server_bandwidth_limit = c.intget("network.bandwidth-limit")
        bandwidthlog("server_bandwidth_limit_change=%s, server_bandwidth_limit=%s", self.server_bandwidth_limit_change, self.server_bandwidth_limit)
        return True

    def process_ui_capabilities(self):
        self.send_deflate_level()
        self.send_ping()
        if self.pings>0:
            self.ping_timer = self.timeout_add(1000*self.pings, self.send_ping)

    def cancel_ping_timer(self):
        pt = self.ping_timer
        if pt:
            self.ping_timer = None
            self.source_remove(pt)

    def cancel_ping_echo_timers(self):
        pet = tuple(self.ping_echo_timers.values())
        self.ping_echo_timers = {}
        for t in pet:
            self.source_remove(t)


    ######################################################################
    # info:
    def _process_info_response(self, packet):
        self.info_request_pending = False
        self.server_last_info = packet[1]
        log("info-response: %s", self.server_last_info)
        if LOG_INFO_RESPONSE:
            items = LOG_INFO_RESPONSE.split(",")
            logres = [re.compile(v) for v in items]
            log.info("info-response debug for %s:", csv(["'%s'" % x for x in items]))
            for k in sorted(self.server_last_info.keys()):
                if any(lr.match(k) for lr in logres):
                    log.info(" %s=%s", k, self.server_last_info[k])

    def send_info_request(self, *categories):
        if not self.info_request_pending:
            self.info_request_pending = True
            window_ids = ()	#no longer used or supported by servers
            self.send("info-request", [self.uuid], window_ids, categories)


    ######################################################################
    # network and status:
    def server_ok(self):
        return self._server_ok

    def check_server_echo(self, ping_sent_time):
        try:
            del self.ping_echo_timers[ping_sent_time]
        except KeyError:
            pass
        if self._protocol is None:
            #no longer connected!
            return False
        last = self._server_ok
        if FAKE_BROKEN_CONNECTION>0:
            self._server_ok = (int(monotonic_time()) % FAKE_BROKEN_CONNECTION) <= (FAKE_BROKEN_CONNECTION//2)
        else:
            self._server_ok = self.last_ping_echoed_time>=ping_sent_time
        if not self._server_ok:
            if not self.ping_echo_timeout_timer:
                self.ping_echo_timeout_timer = self.timeout_add(PING_TIMEOUT*1000, self.check_echo_timeout, ping_sent_time)
        else:
            self.cancel_ping_echo_timeout_timer()
        log("check_server_echo(%s) last=%s, server_ok=%s (last_ping_echoed_time=%s)", ping_sent_time, last, self._server_ok, self.last_ping_echoed_time)
        if last!=self._server_ok:
            self.server_connection_state_change()
        return False

    def cancel_ping_echo_timeout_timer(self):
        pett = self.ping_echo_timeout_timer
        if pett:
            self.ping_echo_timeout_timer = None
            self.source_remove(pett)

    def server_connection_state_change(self):
        log("server_connection_state_change() ok=%s", self._server_ok)

    def check_echo_timeout(self, ping_time):
        self.ping_echo_timeout_timer = None
        log("check_echo_timeout(%s) last_ping_echoed_time=%s", ping_time, self.last_ping_echoed_time)
        if self.last_ping_echoed_time<ping_time:
            #no point trying to use disconnect_and_quit() to tell the server here..
            self.warn_and_quit(EXIT_TIMEOUT, "server ping timeout - waited %s seconds without a response" % PING_TIMEOUT)

    def send_ping(self):
        now_ms = int(1000.0*monotonic_time())
        self.send("ping", now_ms)
        wait = 2.0
        if len(self.server_ping_latency)>0:
            l = [x for _,x in tuple(self.server_ping_latency)]
            avg = sum(l) / len(l)
            wait = min(5, 1.0+avg*2.0)
            log("send_ping() timestamp=%s, average server latency=%.1f, using max wait %.2fs", now_ms, 1000.0*avg, wait)
        t = self.timeout_add(int(1000.0*wait), self.check_server_echo, now_ms)
        self.ping_echo_timers[now_ms] = t
        return True

    def _process_ping_echo(self, packet):
        echoedtime, l1, l2, l3, cl = packet[1:6]
        self.last_ping_echoed_time = echoedtime
        self.check_server_echo(0)
        server_ping_latency = monotonic_time()-echoedtime/1000.0
        self.server_ping_latency.append((monotonic_time(), server_ping_latency))
        self.server_load = l1, l2, l3
        if cl>=0:
            self.client_ping_latency.append((monotonic_time(), cl/1000.0))
        log("ping echo server load=%s, measured client latency=%sms", self.server_load, cl)

    def _process_ping(self, packet):
        echotime = packet[1]
        l1,l2,l3 = 0,0,0
        if POSIX:
            try:
                (fl1, fl2, fl3) = os.getloadavg()
                l1,l2,l3 = int(fl1*1000), int(fl2*1000), int(fl3*1000)
            except (OSError, AttributeError):
                pass
        sl = -1
        if len(self.server_ping_latency)>0:
            _, sl = self.server_ping_latency[-1]
        self.send("ping_echo", echotime, l1, l2, l3, int(1000.0*sl))


    ######################################################################
    # network level packet compression:
    def set_deflate_level(self, level):
        self.compression_level = level
        self.send_deflate_level()

    def send_deflate_level(self):
        self._protocol.set_compression_level(self.compression_level)
        self.send("set_deflate", self.compression_level)


    def send_bandwidth_limit(self):
        bandwidthlog("send_bandwidth_limit() bandwidth-limit=%i", self.bandwidth_limit)
        assert self.server_bandwidth_limit_change
        self.send("bandwidth-limit", self.bandwidth_limit)


    ######################################################################
    # packets:
    def init_authenticated_packet_handlers(self):
        self.set_packet_handlers(self._packet_handlers, {
            "ping":                 self._process_ping,
            "ping_echo":            self._process_ping_echo,
            "info-response":        self._process_info_response,
            })
