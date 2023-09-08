# This file is part of Xpra.
# Copyright (C) 2010-2023 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.
#pylint: disable-msg=E1101

import os
import re
import sys
from time import monotonic
from collections import deque
from typing import Dict, Any, Tuple, Callable
from gi.repository import GLib

from xpra.os_util import POSIX
from xpra.util import envint, envbool, csv, typedict
from xpra.exit_codes import ExitCode
from xpra.net.common import PacketType
from xpra.net.packet_encoding import ALL_ENCODERS
from xpra.client.base.stub_client_mixin import StubClientMixin
from xpra.scripts.config import parse_with_unit
from xpra.log import Logger

log = Logger("network")
bandwidthlog = Logger("bandwidth")

SSH_AGENT : bool = envbool("XPRA_SSH_AGENT", True)
FAKE_BROKEN_CONNECTION : int = envint("XPRA_FAKE_BROKEN_CONNECTION")
PING_TIMEOUT : int = envint("XPRA_PING_TIMEOUT", 60)
MIN_PING_TIMEOUT : int = envint("XPRA_MIN_PING_TIMEOUT", 2)
MAX_PING_TIMEOUT : int = envint("XPRA_MAX_PING_TIMEOUT", 10)
SWALLOW_PINGS : bool = envbool("XPRA_SWALLOW_PINGS", False)
#LOG_INFO_RESPONSE = ("^window.*position", "^window.*size$")
LOG_INFO_RESPONSE : str = os.environ.get("XPRA_LOG_INFO_RESPONSE", "")
AUTO_BANDWIDTH_PCT : int = envint("XPRA_AUTO_BANDWIDTH_PCT", 80)
assert 1<AUTO_BANDWIDTH_PCT<=100, "invalid value for XPRA_AUTO_BANDWIDTH_PCT: %i" % AUTO_BANDWIDTH_PCT

ETHERNET_JITTER : int = envint("XPRA_LOCAL_JITTER", 0)
WAN_JITTER : int = envint("XPRA_WAN_JITTER", 20)
ADSL_JITTER : int = envint("XPRA_WAN_JITTER", 20)
WIRELESS_JITTER : int = envint("XPRA_WIRELESS_JITTER", 1000)

WIFI_LIMIT : int = envint("XPRA_WIFI_LIMIT", 10*1000*1000)
ADSL_LIMIT : int = envint("XPRA_WIFI_LIMIT", 1000*1000)


def get_NM_adapter_type(device_name) -> str:
    if not any (sys.modules.get(f"gi.repository.{mod}") for mod in ("GLib", "Gtk")):
        log("get_NM_adapter_type() no main loop")
        return ""
    try:
        import gi
        gi.require_version("NM", "1.0")
        from gi.repository import NM
    except (ImportError, ValueError):
        log("get_NM_adapter_type() no network-manager bindings")
        return ""
    nmclient = NM.Client.new(None)
    if device_name:
        nmdevice = nmclient.get_device_by_iface(device_name)
    else:
        connection = nmclient.get_primary_connection()
        if not connection:
            return ""
        try:
            nmdevice = connection.get_controller()
        except AttributeError:
            nmdevice = connection.get_master()
    if not nmdevice:
        return ""
    log(f"NM device {device_name!r}: {nmdevice.get_vendor()} {nmdevice.get_product()}")
    nmstate = nmdevice.get_state()
    log(f"NM state({device_name})={nmstate}")
    if nmdevice.get_state() != NM.DeviceState.ACTIVATED:
        log.info(f"ignoring {device_name}: {nmstate.value_name}")
        return ""
    adapter_type = nmdevice.get_device_type().value_name
    log(f"NM device-type({device_name})={adapter_type}")
    return adapter_type


def parse_speed(v):
    return parse_with_unit("speed", v)

def get_device_value(coptions : Dict, device_info : Dict, attr: str, conv: Callable = str, default_value: Any = ""):
    # first try an env var:
    v = os.environ.get("XPRA_NETWORK_%s" % attr.upper().replace("-", "_"))
    # next try device options (ie: from connection URI)
    if v is None:
        v = coptions.get("socket.%s" % attr)
    # last: the OS may know:
    if v is None:
        v = device_info.get(attr)
    if v is not None:
        try:
            return conv(v)
        except (ValueError, TypeError) as e:
            log("get_device_value%s", (coptions, device_info, attr, conv, default_value), exc_info=True)
            log.warn("Warning: invalid value for network attribute '%s'", attr)
            log.warn(" %r: %s", v, e)
    return default_value

def guess_adapter_type(name:str) -> str:
    dnl = name.lower()
    if dnl.startswith("wlan") or dnl.startswith("wlp") or any(dnl.find(x) >= 0 for x in ("wireless", "wlan", "80211", "modem")):
        return "wireless"
    if dnl == "lo" or dnl.find("loopback") >= 0 or dnl.startswith("local"):
        return "loopback"
    if any(dnl.find(x) >= 0 for x in ("fiber", "1394", "infiniband", "tun", "tap", "vlan")):
        return "local"
    if any(dnl.find(x) >= 0 for x in ("ether", "local", "fiber", "1394", "infiniband", "veth")):
        return "ethernet"
    if dnl.find("wan") >= 0:
        return "wan"
    return ""

def jitter_for_adapter_type(adapter_type:str) -> int:
    if not adapter_type:
        return -1
    at = adapter_type.lower()
    def anyfind(*args):
        return any(at.find(str(x))>=0 for x in args)
    if anyfind("loopback"):
        return 0
    if anyfind("ether", "local", "fiber", "1394", "infiniband"):
        return ETHERNET_JITTER
    if at.find("wan") >= 0:
        return WAN_JITTER
    if anyfind("wireless", "wifi", "wimax", "modem", "mesh"):
        return WIRELESS_JITTER
    return -1

def guess_bandwidth_limit(adapter_type:str) -> int:
    at = adapter_type.lower()
    def anyfind(*args):
        return any(at.find(str(x))>=0 for x in args)
    if anyfind("wireless", "wifi", "wimax", "modem"):
        return WIFI_LIMIT
    if anyfind("adsl", "ppp"):
        return ADSL_LIMIT
    return 0


class NetworkState(StubClientMixin):
    """
    Mixin for adding server / network state monitoring functions:
    - ping and echo
    - info request and response
    """

    def __init__(self):
        super().__init__()
        self.server_start_time : float = -1
        #legacy:
        self.compression_level : int = 0

        #setting:
        self.pings : bool = False

        #bandwidth
        self.bandwidth_limit : int = 0
        self.bandwidth_detection : bool = False
        self.server_bandwidth_limit_change : bool = False
        self.server_bandwidth_limit : int = 0
        self.server_session_name : str = ""

        #info requests
        self.server_last_info : Dict = {}
        self.info_request_pending : bool = False

        #network state:
        self.server_packet_encoders : Tuple[str, ...] = ()
        self.server_ping_latency : deque[Tuple[float,float]] = deque(maxlen=1000)
        self.server_load = (0, 0, 0)
        self.client_ping_latency : deque[Tuple[float,float]] = deque(maxlen=1000)
        self._server_ok : bool = True
        self.last_ping_echoed_time = 0
        self.ping_timer : int = 0
        self.ping_echo_timers : Dict[int,int] = {}
        self.ping_echo_timeout_timer = 0


    def init(self, opts) -> None:
        self.pings = opts.pings
        self.bandwidth_limit = parse_with_unit("bandwidth-limit", opts.bandwidth_limit)
        self.bandwidth_detection = opts.bandwidth_detection
        bandwidthlog("init bandwidth_limit=%s", self.bandwidth_limit)


    def cleanup(self) -> None:
        self.cancel_ping_timer()
        self.cancel_ping_echo_timers()
        self.cancel_ping_echo_timeout_timer()


    def get_info(self) -> Dict[str,Any]:
        return {
            "network" : {
                "bandwidth-limit"       : self.bandwidth_limit,
                "bandwidth-detection"   : self.bandwidth_detection,
                "server-ok"             : self._server_ok,
                }
            }

    def get_caps(self) -> Dict[str,Any]:
        caps : Dict[str, Any] = {
            "network-state" : True,
            "info-namespace" : True,            #v4 servers assume this is always supported
            }
        ssh_auth_sock = os.environ.get("SSH_AUTH_SOCK")
        if SSH_AGENT and ssh_auth_sock and os.path.isabs(ssh_auth_sock):
            #ensure agent forwarding is actually requested?
            #(checking the socket type is not enough:
            # one could still bind mount the path and connect via tcp! why though?)
            #meh: if the transport doesn't have agent forwarding enabled,
            # then it won't create a server-side socket
            # and nothing will happen,
            # exposing this client-side path is no big deal
            caps["ssh-auth-sock"] = ssh_auth_sock
        #get socket speed if we have it:
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
        if jitter>=0:
            connection_data["jitter"] = jitter
        if socket_speed:
            connection_data["speed"] = socket_speed
        log("get_caps() connection-data=%s", connection_data)
        caps["connection-data"] = connection_data

        bandwidth_limit = self.bandwidth_limit
        bandwidthlog("bandwidth-limit setting=%s, socket-speed=%s", self.bandwidth_limit, socket_speed)
        if bandwidth_limit is None:
            if socket_speed:
                #auto: use 80% of socket speed if we have it:
                bandwidth_limit = socket_speed*AUTO_BANDWIDTH_PCT//100 or 0
            else:
                bandwidth_limit = guess_bandwidth_limit(adapter_type)
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
        self.server_bandwidth_limit_change = c.boolget("network.bandwidth-limit-change", True)
        self.server_bandwidth_limit = c.intget("network.bandwidth-limit")
        bandwidthlog("server_bandwidth_limit_change=%s, server_bandwidth_limit=%s",
                     self.server_bandwidth_limit_change, self.server_bandwidth_limit)
        self.server_packet_encoders = tuple(x for x in ALL_ENCODERS if c.boolget(x, False))
        return True

    def process_ui_capabilities(self, caps : typedict) -> None:
        self.send_deflate_level()
        self.send_ping()
        if self.pings>0:
            self.ping_timer = GLib.timeout_add(1000*self.pings, self.send_ping)

    def cancel_ping_timer(self) -> None:
        pt = self.ping_timer
        if pt:
            self.ping_timer = 0
            GLib.source_remove(pt)

    def cancel_ping_echo_timers(self) -> None:
        pet : Tuple[int,...] = tuple(self.ping_echo_timers.values())
        self.ping_echo_timers = {}
        for t in pet:
            GLib.source_remove(t)


    ######################################################################
    # info:
    def _process_info_response(self, packet : PacketType) -> None:
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

    def send_info_request(self, *categories) -> None:
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
        self._server_ok = self.last_ping_echoed_time >= ping_sent_time
        if FAKE_BROKEN_CONNECTION>0:
            self._server_ok = self._server_ok and (int(monotonic()) % FAKE_BROKEN_CONNECTION) <= (FAKE_BROKEN_CONNECTION//2)
        if not self._server_ok:
            if not self.ping_echo_timeout_timer:
                self.ping_echo_timeout_timer = GLib.timeout_add(PING_TIMEOUT*1000,
                                                                self.check_echo_timeout, ping_sent_time)
        else:
            self.cancel_ping_echo_timeout_timer()
        log("check_server_echo(%s) last=%s, server_ok=%s (last_ping_echoed_time=%s)",
            ping_sent_time, last, self._server_ok, self.last_ping_echoed_time)
        if last!=self._server_ok:
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
        log("check_echo_timeout(%s) last_ping_echoed_time=%s", ping_time, self.last_ping_echoed_time)
        if self.last_ping_echoed_time<ping_time:
            #no point trying to use disconnect_and_quit() to tell the server here..
            self.warn_and_quit(ExitCode.CONNECTION_LOST, "server ping timeout - waited %s seconds without a response" % PING_TIMEOUT)

    def send_ping(self) -> bool:
        p = self._protocol
        if not p or p.TYPE not in ("xpra", "websocket"):
            self.ping_timer = 0
            return False
        now_ms = int(1000.0*monotonic())
        self.send("ping", now_ms)
        wait = 1000*MIN_PING_TIMEOUT
        aspl = tuple(self.server_ping_latency)
        if aspl:
            spl : Tuple[float,...] = tuple(x[1] for x in aspl)
            avg = sum(spl) / len(spl)
            wait = max(1000*MIN_PING_TIMEOUT, min(1000*MAX_PING_TIMEOUT, round(1000+avg*2000)))
            log("send_ping() timestamp=%s, average server latency=%ims, using max wait %ims",
                now_ms, round(1000*avg), wait)
        t = GLib.timeout_add(wait, self.check_server_echo, now_ms)
        self.ping_echo_timers[now_ms] = t
        return True

    def _process_ping_echo(self, packet : PacketType) -> None:
        echoedtime, l1, l2, l3, cl = packet[1:6]
        self.last_ping_echoed_time = echoedtime
        self.check_server_echo(0)
        server_ping_latency = monotonic()-echoedtime/1000.0
        self.server_ping_latency.append((monotonic(), server_ping_latency))
        self.server_load = l1, l2, l3
        if cl>=0:
            self.client_ping_latency.append((monotonic(), cl/1000.0))
        log("ping echo server load=%s, measured client latency=%sms", self.server_load, cl)

    def _process_ping(self, packet : PacketType) -> None:
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
    def set_deflate_level(self, level:int) -> None:
        self.compression_level = level
        self.send_deflate_level()

    def send_deflate_level(self) -> None:
        p = self._protocol
        if p and p.TYPE=="xpra":
            self._protocol.set_compression_level(self.compression_level)
            self.send("set_deflate", self.compression_level)


    def send_bandwidth_limit(self) -> None:
        bandwidthlog("send_bandwidth_limit() bandwidth-limit=%i", self.bandwidth_limit)
        assert self.server_bandwidth_limit_change, self.bandwidth_limit is not None
        self.send("bandwidth-limit", self.bandwidth_limit)


    ######################################################################
    # packets:
    def init_authenticated_packet_handlers(self) -> None:
        self.add_packet_handler("ping", self._process_ping, False)
        self.add_packet_handler("ping_echo", self._process_ping_echo, False)
        self.add_packet_handler("info-response", self._process_info_response, False)
