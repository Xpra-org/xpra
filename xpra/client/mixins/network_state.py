# This file is part of Xpra.
# Copyright (C) 2010-2020 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.
#pylint: disable-msg=E1101

import os
import re
from time import monotonic
from collections import deque

from xpra.os_util import POSIX
from xpra.util import envint, envbool, csv, typedict
from xpra.exit_codes import EXIT_CONNECTION_LOST
from xpra.net.packet_encoding import ALL_ENCODERS
from xpra.client.mixins.stub_client_mixin import StubClientMixin
from xpra.scripts.config import parse_with_unit
from xpra.log import Logger

log = Logger("network")
bandwidthlog = Logger("bandwidth")

FAKE_BROKEN_CONNECTION = envint("XPRA_FAKE_BROKEN_CONNECTION")
PING_TIMEOUT = envint("XPRA_PING_TIMEOUT", 60)
MIN_PING_TIMEOUT = envint("XPRA_MIN_PING_TIMEOUT", 2)
MAX_PING_TIMEOUT = envint("XPRA_MAX_PING_TIMEOUT", 10)
SWALLOW_PINGS = envbool("XPRA_SWALLOW_PINGS", False)
#LOG_INFO_RESPONSE = ("^window.*position", "^window.*size$")
LOG_INFO_RESPONSE = os.environ.get("XPRA_LOG_INFO_RESPONSE", "")
AUTO_BANDWIDTH_PCT = envint("XPRA_AUTO_BANDWIDTH_PCT", 80)
assert 1<AUTO_BANDWIDTH_PCT<=100, "invalid value for XPRA_AUTO_BANDWIDTH_PCT: %i" % AUTO_BANDWIDTH_PCT

LOCAL_JITTER = envint("XPRA_LOCAL_JITTER", 0)
WAN_JITTER = envint("XPRA_WAN_JITTER", 20)
WIRELESS_JITTER = envint("XPRA_WIRELESS_JITTER", 1000)


class NetworkState(StubClientMixin):
    """
    Mixin for adding server / network state monitoring functions:
    - ping and echo
    - info request and response
    """

    def __init__(self):
        super().__init__()
        self.server_start_time = -1
        #legacy:
        self.compression_level = 0

        #setting:
        self.pings = False

        #bandwidth
        self.bandwidth_limit = 0
        self.bandwidth_detection = True
        self.server_bandwidth_limit_change = False
        self.server_bandwidth_limit = 0
        self.server_session_name = None

        #info requests
        self.server_last_info = None
        self.info_request_pending = False

        #network state:
        self.server_packet_encoders = ()
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
        self.bandwidth_detection = opts.bandwidth_detection
        bandwidthlog("init bandwidth_limit=%s", self.bandwidth_limit)


    def cleanup(self):
        self.cancel_ping_timer()
        self.cancel_ping_echo_timers()
        self.cancel_ping_echo_timeout_timer()


    def get_info(self) -> dict:
        return {
            "network" : {
                "bandwidth-limit"       : self.bandwidth_limit,
                "bandwidth-detection"   : self.bandwidth_detection,
                "server-ok"             : self._server_ok,
                }
            }

    def get_caps(self) -> dict:
        caps = {
            "network-state" : True,
            "info-namespace" : True,            #v4 servers assume this is always supported
            }
        #get socket speed if we have it:
        pinfo = self._protocol.get_info()
        device_info = pinfo.get("socket", {}).get("device", {})
        connection_data = {}
        try:
            coptions = self._protocol._conn.options
        except AttributeError:
            coptions = {}
        log("get_caps() device_info=%s, connection options=%s", device_info, coptions)
        def device_value(attr, conv=str, default_value=""):
            #first try an env var:
            v = os.environ.get("XPRA_NETWORK_%s" % attr.upper().replace("-", "_"))
            #next try device options (ie: from connection URI)
            if v is None:
                v = coptions.get("socket.%s" % attr)
            #last: the OS may know:
            if v is None:
                v = device_info.get(attr)
            if v is not None:
                try:
                    return conv(v)
                except (ValueError, TypeError) as e:
                    log("device_value%s", (attr, conv, default_value), exc_info=True)
                    log.warn("Warning: invalid value for network attribute '%s'", attr)
                    log.warn(" %r: %s", v, e)
            return default_value
        def parse_speed(v):
            return parse_with_unit("speed", v)
        #network interface speed:
        socket_speed = device_value("speed", parse_speed, 0)
        log("get_caps() found socket_speed=%s", socket_speed)
        if socket_speed:
            connection_data["speed"] = socket_speed
        default_adapter_type = device_value("adapter-type")
        log("get_caps() found default adapter-type=%s", default_adapter_type)
        device_name = device_value("name")
        log("get_caps() found device name=%s", device_name)
        jitter = device_value("jitter", int, -1)
        if jitter<0:
            at = default_adapter_type.lower()
            if device_name.startswith("wlan") or device_name.startswith("wlp") or device_name.find("wifi")>=0:
                jitter = WIRELESS_JITTER
                device_info["adapter-type"] = "wireless"
            elif device_name=="lo":
                jitter = LOCAL_JITTER
                device_info["adapter-type"] = "loopback"
            elif any(at.find(x)>=0 for x in ("ether", "local", "fiber", "1394", "infiniband")):
                jitter = LOCAL_JITTER
            elif at.find("wan")>=0:
                jitter = WAN_JITTER
            elif at.find("wireless")>=0 or at.find("wlan")>=0 or at.find("wifi")>=0 or at.find("80211")>=0:
                jitter = WIRELESS_JITTER
        if jitter>=0:
            connection_data["jitter"] = jitter
        adapter_type = device_value("adapter-type", str, default_adapter_type)
        if adapter_type:
            connection_data["adapter-type"] = adapter_type
        log("get_caps() connection-data=%s", connection_data)
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
        caps["bandwidth-detection"] = self.bandwidth_detection
        caps["ping-echo-sourceid"] = True
        return caps

    def parse_server_capabilities(self, c : typedict) -> bool:
        #make sure the server doesn't provide a start time in the future:
        import time
        self.server_start_time = min(time.time(), c.intget("start_time", -1))
        self.server_bandwidth_limit_change = c.boolget("network.bandwidth-limit-change")
        self.server_bandwidth_limit = c.intget("network.bandwidth-limit")
        bandwidthlog("server_bandwidth_limit_change=%s, server_bandwidth_limit=%s",
                     self.server_bandwidth_limit_change, self.server_bandwidth_limit)
        self.server_packet_encoders = tuple(x for x in ALL_ENCODERS if c.boolget(x, False))
        return True

    def process_ui_capabilities(self, caps : typedict):
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
                if LOG_INFO_RESPONSE=="all" or any(lr.match(k) for lr in logres):
                    log.info(" %s=%s", k, self.server_last_info[k])

    def send_info_request(self, *categories):
        if not self.info_request_pending:
            self.info_request_pending = True
            window_ids = () #no longer used or supported by servers
            self.send("info-request", [self.uuid], window_ids, categories)


    ######################################################################
    # network and status:
    def server_ok(self) -> bool:
        return self._server_ok

    def check_server_echo(self, ping_sent_time):
        self.ping_echo_timers.pop(ping_sent_time, None)
        if self._protocol is None:
            #no longer connected!
            return False
        last = self._server_ok
        if FAKE_BROKEN_CONNECTION>0:
            self._server_ok = (int(monotonic()) % FAKE_BROKEN_CONNECTION) <= (FAKE_BROKEN_CONNECTION//2)
        else:
            self._server_ok = self.last_ping_echoed_time>=ping_sent_time
        if not self._server_ok:
            if not self.ping_echo_timeout_timer:
                self.ping_echo_timeout_timer = self.timeout_add(PING_TIMEOUT*1000,
                                                                self.check_echo_timeout, ping_sent_time)
        else:
            self.cancel_ping_echo_timeout_timer()
        log("check_server_echo(%s) last=%s, server_ok=%s (last_ping_echoed_time=%s)",
            ping_sent_time, last, self._server_ok, self.last_ping_echoed_time)
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
            self.warn_and_quit(EXIT_CONNECTION_LOST, "server ping timeout - waited %s seconds without a response" % PING_TIMEOUT)

    def send_ping(self):
        p = self._protocol
        if not p or p.TYPE!="xpra":
            self.ping_timer = None
            return False
        now_ms = int(1000.0*monotonic())
        self.send("ping", now_ms)
        wait = 2.0
        spl = tuple(self.server_ping_latency)
        if spl:
            spl = tuple(x[1] for x in spl)
            avg = sum(spl) / len(spl)
            wait = max(MIN_PING_TIMEOUT, min(MAX_PING_TIMEOUT, 1.0+avg*2.0))
            log("send_ping() timestamp=%s, average server latency=%.1f, using max wait %.2fs",
                now_ms, 1000.0*avg, wait)
        t = self.timeout_add(int(1000.0*wait), self.check_server_echo, now_ms)
        self.ping_echo_timers[now_ms] = t
        return True

    def _process_ping_echo(self, packet):
        echoedtime, l1, l2, l3, cl = packet[1:6]
        self.last_ping_echoed_time = echoedtime
        self.check_server_echo(0)
        server_ping_latency = monotonic()-echoedtime/1000.0
        self.server_ping_latency.append((monotonic(), server_ping_latency))
        self.server_load = l1, l2, l3
        if cl>=0:
            self.client_ping_latency.append((monotonic(), cl/1000.0))
        log("ping echo server load=%s, measured client latency=%sms", self.server_load, cl)

    def _process_ping(self, packet):
        echotime = packet[1]
        l1,l2,l3 = 0,0,0
        sid = ""
        if len(packet)>=4:
            sid = packet[3]
        if POSIX:
            try:
                (fl1, fl2, fl3) = os.getloadavg()
                l1,l2,l3 = int(fl1*1000), int(fl2*1000), int(fl3*1000)
            except (OSError, AttributeError):
                pass
        try:
            sl = self.server_ping_latency[-1][1]
        except IndexError:
            sl = -1
        if SWALLOW_PINGS>0:
            return
        self.send("ping_echo", echotime, l1, l2, l3, int(1000.0*sl), sid)


    ######################################################################
    # network level packet compression:
    def set_deflate_level(self, level):
        self.compression_level = level
        self.send_deflate_level()

    def send_deflate_level(self):
        p = self._protocol
        if p and p.TYPE=="xpra":
            self._protocol.set_compression_level(self.compression_level)
            self.send("set_deflate", self.compression_level)


    def send_bandwidth_limit(self):
        bandwidthlog("send_bandwidth_limit() bandwidth-limit=%i", self.bandwidth_limit)
        assert self.server_bandwidth_limit_change, self.bandwidth_limit is not None
        self.send("bandwidth-limit", self.bandwidth_limit)


    ######################################################################
    # packets:
    def init_authenticated_packet_handlers(self):
        self.add_packet_handler("ping", self._process_ping, False)
        self.add_packet_handler("ping_echo", self._process_ping_echo, False)
        self.add_packet_handler("info-response", self._process_info_response, False)
