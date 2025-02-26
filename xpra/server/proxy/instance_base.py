# This file is part of Xpra.
# Copyright (C) 2013 Antoine Martin <antoine@xpra.org>
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import socket
from time import sleep, time, monotonic
from queue import Queue
from typing import Any
from collections.abc import Callable, Iterable

from xpra.net.net_util import get_network_caps
from xpra.net.compression import Compressed, compressed_wrapper, MIN_COMPRESS_SIZE
from xpra.net.protocol.constants import CONNECTION_LOST
from xpra.net.common import MAX_PACKET_SIZE, PacketType
from xpra.net.digest import get_salt, gendigest
from xpra.scripts.config import parse_number, str_to_bool
from xpra.common import FULL_INFO, ConnectionMessage
from xpra.os_util import get_hex_uuid, gi_import
from xpra.exit_codes import ExitValue
from xpra.util.objects import typedict
from xpra.util.str_fn import csv, Ellipsizer, strtobytes, nicestr
from xpra.util.env import envint, envbool
from xpra.util.version import XPRA_VERSION, vparts
from xpra.server.core import get_server_info, get_thread_info, proto_crypto_caps
from xpra.log import Logger

GLib = gi_import("GLib")

log = Logger("proxy")

PROXY_QUEUE_SIZE = envint("XPRA_PROXY_QUEUE_SIZE", 0)
PASSTHROUGH_AUTH = envbool("XPRA_PASSTHROUGH_AUTH", True)

PING_INTERVAL = max(1, envint("XPRA_PROXY_PING_INTERVAL", 5)) * 1000
PING_WARNING = max(5, envint("XPRA_PROXY_PING_WARNING", 5))
PING_TIMEOUT = max(5, envint("XPRA_PROXY_PING_TIMEOUT", 90))

CLIENT_REMOVE_CAPS = ("cipher", "challenge", "digest", "aliases", "compression", "lz4", "lz0", "zlib")
CLIENT_REMOVE_CAPS_CHALLENGE = ("cipher", "digest", "aliases", "compression", "lz4", "lz0", "zlib")


def number(k, v) -> int:
    return parse_number(int, k, v)


SESSION_OPTION_WHITELIST: dict[str, Callable] = {
    "compression_level": number,
    "lz4": str_to_bool,
    "rencodeplus": str_to_bool,
}


def sanitize_session_options(options: dict[str, str]) -> dict[str, Any]:
    d = {}
    for k, v in options.items():
        parser = SESSION_OPTION_WHITELIST.get(k)
        if parser:
            log("trying to add %s=%s using %s", k, v, parser)
            try:
                d[k] = parser(k, v)
            except Exception as e:
                log.warn("failed to parse value %s for %s using %s: %s", v, k, parser, e)
    return d


def filter_caps(caps: typedict, prefixes: Iterable[str], proto=None) -> dict:
    # removes caps that overrides / does not use:
    pcaps = {}
    removed = []
    for k in caps.keys():
        if any(e for e in prefixes if str(k).startswith(e)):
            removed.append(k)
        else:
            pcaps[k] = caps[k]
    log("filtered out %s matching %s", removed, prefixes)
    # replace the network caps with the proxy's own:
    pcaps |= get_network_caps() | proto_crypto_caps(proto)
    # then add the proxy info:
    si = get_server_info()
    if FULL_INFO > 0:
        si["hostname"] = socket.gethostname()
    pcaps["proxy"] = si
    return pcaps


def replace_packet_item(packet: PacketType,
                        index: int,
                        new_value: Compressed | str | dict | int) -> PacketType:
    # make the packet data mutable and replace the contents at `index`:
    assert index > 0
    lpacket = list(packet)
    lpacket[index] = new_value
    # noinspection PyTypeChecker
    return tuple(lpacket)


# noinspection PyMethodMayBeStatic
class ProxyInstance:

    def __init__(self, session_options: dict[str, str],
                 pings: int,
                 disp_desc: dict, cipher: str, cipher_mode: str, encryption_key: bytes, caps: typedict):
        self.session_options = session_options
        self.pings = pings
        self.disp_desc = disp_desc
        self.cipher = cipher
        self.cipher_mode = cipher_mode
        self.encryption_key = encryption_key
        self.caps = caps
        log("ProxyInstance%s", (
            session_options,
            disp_desc, cipher, cipher_mode, encryption_key,
            "%s: %s.." % (type(caps), Ellipsizer(caps))))
        self.uuid: str = get_hex_uuid()
        self.client_protocol = None
        self.client_has_more = False
        self.server_protocol = None
        self.server_has_more = False
        # ping handling:
        self.client_last_ping: float = 0
        self.server_last_ping: float = 0
        self.client_last_ping_echo: float = 0
        self.server_last_ping_echo: float = 0
        self.client_last_ping_latency: float = 0
        self.server_last_ping_latency: float = 0
        self.client_ping_timer = 0
        self.server_ping_timer = 0
        self.client_challenge_packet: tuple = ()
        self.exit = False
        self.server_packets: Queue[PacketType] = Queue(PROXY_QUEUE_SIZE)
        self.client_packets: Queue[PacketType] = Queue(PROXY_QUEUE_SIZE)

    def is_alive(self) -> bool:
        return not self.exit

    def log_start(self) -> None:
        assert self.client_protocol and self.server_protocol
        log.info("started %s", self)
        log.info(" for client %s", self.client_protocol._conn)
        log.info(" and server %s", self.server_protocol._conn)

    def run(self) -> ExitValue:
        # server connection tweaks:
        self.server_protocol.large_packets += ["input-devices", "draw", "window-icon",
                                               "keymap-changed", "server-settings"]
        if self.caps.boolget("file-transfer"):
            self.server_protocol.large_packets += ["send-file", "send-file-chunk"]
            self.client_protocol.large_packets += ["send-file", "send-file-chunk"]
        self.server_protocol.set_compression_level(int(self.session_options.get("compression_level", 0)))
        self.server_protocol.enable_default_encoder()

        self.start_network_threads()
        self.schedule_client_ping()

        self.send_hello()
        return 0

    def start_network_threads(self) -> None:
        raise NotImplementedError()

    ################################################################################

    def close_connections(self, skip_proto, *reasons) -> None:
        for proto in (self.client_protocol, self.server_protocol):
            if proto and proto != skip_proto:
                log("sending disconnect to %s", proto)
                rstr = [nicestr(reason) for reason in reasons]
                proto.send_disconnect([ConnectionMessage.SERVER_SHUTDOWN] + rstr)
        # wait for connections to close down cleanly before we exit
        cp = self.client_protocol
        sp = self.server_protocol
        for i in range(10):
            if cp.is_closed() and sp.is_closed():
                return
            if i == 0:
                log("waiting for network connections to close")
            elif i == 1:
                log.info("waiting for network connections to close")
            else:
                log("still waiting %i/10 - client.closed=%s, server.closed=%s",
                    i + 1, cp.is_closed(), sp.is_closed())
            sleep(0.1)
        if not cp.is_closed():
            log("proxy instance client connection has not been closed yet:")
            log(" %s", cp)
            cp.close()
        if not sp.is_closed():
            log("proxy instance server connection has not been closed yet:")
            log(" %s", sp)
            sp.close()

    def send_disconnect(self, proto, *reasons) -> None:
        log("send_disconnect(%s, %s)", proto, reasons)
        if proto.is_closed():
            return
        proto.send_disconnect(reasons)
        self.timeout_add(1000, self.force_disconnect, proto)

    def force_disconnect(self, proto) -> None:
        proto.close()

    def stop(self, skip_proto, *reasons) -> None:
        log("stop(%s, %s)", skip_proto, reasons)
        if not self.exit:
            log.info("stopping %s", self)
            for x in reasons:
                log.info(" %s", x)
            self.exit = True
        self.cancel_client_ping_timer()
        self.cancel_server_ping_timer()
        self.close_connections(skip_proto, *reasons)
        self.stopped()

    def stopped(self) -> None:
        pass

    ################################################################################

    def get_proxy_info(self, proto) -> dict[str, Any]:
        sinfo = {"threads": get_thread_info(proto)}
        sinfo.update(get_server_info())
        linfo = {}
        if self.client_last_ping_latency:
            linfo["client"] = round(self.client_last_ping_latency)
        if self.server_last_ping_latency:
            linfo["server"] = round(self.server_last_ping_latency)
        return {
            "proxy": {
                "version": vparts(XPRA_VERSION, FULL_INFO + 1),
                "": sinfo,
                "latency": linfo,
            },
        }

    def get_connection_info(self) -> dict[str, Any]:
        return {
            "client": self.client_protocol.get_info(),
            "server": self.server_protocol.get_info(),
        }

    def get_info(self) -> dict[str, Any]:
        return {"connection": self.get_connection_info()}

    ################################################################################

    def send_hello(self, challenge_response=b"", client_salt=b"") -> None:
        hello = self.filter_client_caps()
        if challenge_response:
            hello.update({
                "challenge_response": challenge_response,
                "challenge_client_salt": client_salt,
            })
        hello.setdefault("network", {})["pings"] = self.pings
        self.queue_server_packet(("hello", hello))

    def filter_client_caps(self, remove=CLIENT_REMOVE_CAPS) -> dict:
        fc = filter_caps(self.caps, remove, self.server_protocol)
        # the display string may override the username:
        username = self.disp_desc.get("username")
        if username:
            fc["username"] = username
        # update with options provided via config if any:
        fc.update(sanitize_session_options(self.session_options))
        return fc

    def filter_server_caps(self, caps: typedict) -> dict:
        self.server_protocol.enable_encoder_from_caps(caps)
        return filter_caps(caps, ("aliases",), self.client_protocol)

    ################################################################################

    def queue_client_packet(self, packet: PacketType) -> None:
        log("queueing client packet: %s (queue size=%s)", packet[0], self.client_packets.qsize())
        self.client_packets.put(packet)
        self.client_protocol.source_has_more()

    def get_client_packet(self) -> tuple[PacketType, bool, bool]:
        # server wants a packet
        p = self.client_packets.get()
        s = self.client_packets.qsize()
        log("sending to client: %s (queue size=%i)", p[0], s)
        return p, True, s > 0 or self.server_has_more

    def process_client_packet(self, proto, packet: PacketType) -> None:
        packet_type = str(packet[0])
        log("process_client_packet: %s", packet_type)
        if packet_type == CONNECTION_LOST:
            self.stop(proto, "client connection lost")
            return
        self.client_has_more = proto.receive_pending
        if packet_type == "hello":
            if not self.client_challenge_packet:
                log.warn("Warning: invalid hello packet from client")
                log.warn(" received after initial authentication (dropped)")
                return
            log("forwarding client hello")
            log(" for challenge packet %s", self.client_challenge_packet)
            # update caps with latest hello caps from client:
            self.caps = typedict(packet[1])
            # keep challenge data in the hello response:
            hello = self.filter_client_caps(CLIENT_REMOVE_CAPS_CHALLENGE)
            self.queue_server_packet(("hello", hello))
            return
        if packet_type == "ping_echo" and self.client_ping_timer and len(packet) >= 7 and packet[6] == self.uuid:
            # this is one of our ping packets:
            self.client_last_ping_echo = float(packet[1])
            self.client_last_ping_latency = 1000 * monotonic() - self.client_last_ping_echo
            log("ping-echo: client latency=%.1fms", self.client_last_ping_latency)
            return
        # the packet types below are forwarded:
        if packet_type == "disconnect":
            reasons = tuple(str(x) for x in packet[1:])
            log("got disconnect from client: %s", csv(reasons))
            if self.exit:
                self.client_protocol.close()
            else:
                self.stop(None, "disconnect from client", *reasons)
        elif packet_type == "send-file" and packet[6]:
            packet = self.compressed_marker(packet, 6, "file-data")
        elif packet_type == "send-file-chunk" and packet[3]:
            packet = self.compressed_marker(packet, 3, "file-chunk-data")
        self.queue_server_packet(packet)

    def compressed_marker(self, packet: PacketType, index: int, description: str) -> PacketType:
        return replace_packet_item(packet, index, Compressed(description, packet[index]))

    def queue_server_packet(self, packet: PacketType) -> None:
        log("queueing server packet: %s (queue size=%s)", packet[0], self.server_packets.qsize())
        self.server_packets.put(packet)
        self.server_protocol.source_has_more()

    def get_server_packet(self):
        # server wants a packet
        p = self.server_packets.get()
        s = self.server_packets.qsize()
        log("sending to server: %s (queue size=%i)", p[0], s)
        return p, True, s > 0 or self.client_has_more

    def _packet_recompress(self, packet: PacketType, index: int, name: str) -> PacketType:
        if len(packet) <= index:
            return packet
        data = packet[index]
        if len(data) < MIN_COMPRESS_SIZE:
            return packet
        # this is ugly and not generic!
        kw = {"lz4": self.caps.boolget("lz4")}
        return replace_packet_item(packet, index, compressed_wrapper(name, data, can_inline=False, **kw))

    def cancel_server_ping_timer(self) -> None:
        spt = self.server_ping_timer
        log("cancel_server_ping_timer() server_ping_timer=%s", spt)
        if spt:
            self.server_ping_timer = 0
            self.source_remove(spt)

    def cancel_client_ping_timer(self) -> None:
        cpt = self.client_ping_timer
        log("cancel_client_ping_timer() client_ping_timer=%s", cpt)
        if cpt:
            self.client_ping_timer = 0
            self.source_remove(cpt)

    def schedule_server_ping(self) -> None:
        log("schedule_server_ping()")
        self.cancel_server_ping_timer()
        self.server_last_ping_echo = monotonic()
        self.server_ping_timer = self.timeout_add(PING_INTERVAL, self.send_server_ping)

    def schedule_client_ping(self) -> None:
        log("schedule_client_ping()")
        self.cancel_client_ping_timer()
        self.client_last_ping_echo = monotonic()
        self.client_ping_timer = self.timeout_add(PING_INTERVAL, self.send_client_ping)

    def send_server_ping(self) -> bool:
        log("send_server_ping() server_last_ping=%s", self.server_last_ping)
        # if we've already sent one, check for the echo:
        if self.server_last_ping:
            delta = self.server_last_ping - self.server_last_ping_echo
            if delta > PING_WARNING:
                log.warn("Warning: late server ping, %i seconds", delta)
            if delta > PING_TIMEOUT:
                log.error("Error: server ping timeout, %i seconds", delta)
                self.stop(None, "proxy to server ping timeout")
                return False
        now = monotonic()
        self.server_last_ping = now
        packet: PacketType = ("ping", int(now * 1000), int(time() * 1000), self.uuid)
        self.queue_server_packet(packet)
        return True

    def send_client_ping(self) -> bool:
        log("send_client_ping() client_last_ping=%s", self.client_last_ping)
        # if we've already sent one, check for the echo:
        if self.client_last_ping:
            delta = self.client_last_ping - self.client_last_ping_echo
            if delta > PING_WARNING:
                log.warn("Warning: late client ping, %i seconds", delta)
            if delta > PING_TIMEOUT:
                log.error("Error: client ping timeout, %i seconds", delta)
                self.stop(None, "proxy to client ping timeout")
                return False
        now = monotonic()
        self.client_last_ping = now
        packet: PacketType = ("ping", int(now * 1000), int(time() * 1000), self.uuid)
        self.queue_client_packet(packet)
        return True

    def process_server_packet(self, proto, packet: PacketType) -> None:
        packet_type = str(packet[0])
        log("process_server_packet: %s", packet_type)
        if packet_type == CONNECTION_LOST:
            self.stop(proto, "server connection lost")
            return
        self.server_has_more = proto.receive_pending
        if packet_type == "disconnect":
            reason = str(packet[1])
            log("got disconnect from server: %s", reason)
            if self.exit:
                self.server_protocol.close()
            else:
                self.stop(None, "disconnect from server", reason)
        elif packet_type == "hello":
            c = typedict(packet[1])
            self.schedule_server_ping()
            maxw, maxh = c.intpair("max_desktop_size") or (4096, 4096)
            caps = self.filter_server_caps(c)
            # add new encryption caps:
            if self.cipher:
                # pylint: disable=import-outside-toplevel
                from xpra.net.crypto import crypto_backend_init, new_cipher_caps, DEFAULT_PADDING
                crypto_backend_init()
                enc_caps = self.caps.dictget("encryption")
                padding_options = typedict(enc_caps or {}).strtupleget("padding.options", [DEFAULT_PADDING])
                caps["encryption"] = new_cipher_caps(self.client_protocol,
                                                     self.cipher, self.cipher_mode, self.encryption_key,
                                                     padding_options,
                                                     enc_caps.boolget("always-pad", False),
                                                     enc_caps.boolget("stream", True))
            # may need to bump packet size:
            proto.max_packet_size = max(MAX_PACKET_SIZE, maxw * maxh * 4 * 4)
            packet = ("hello", caps)
        elif packet_type == "ping_echo" and self.server_ping_timer and len(packet) >= 7 and packet[6] == self.uuid:
            # this is one of our ping packets:
            self.server_last_ping_echo = float(packet[1])
            self.server_last_ping_latency = 1000 * monotonic() - self.server_last_ping_echo
            log("ping-echo: server latency=%.1fms", self.server_last_ping_latency)
            return
        elif packet_type == "info-response":
            # adds proxy info:
            # note: this is only seen by the client application
            # "xpra info" is a new connection, which talks to the proxy server...
            info = packet[1]
            info.update(self.get_proxy_info(proto))
        elif packet_type == "draw":
            pixel_data = packet[7]
            if pixel_data and len(pixel_data) > 1024:
                packet = self.compressed_marker(packet, 7, "pixel-data")
        elif packet_type == "sound-data":
            if packet[2]:
                # best if we use raw packets for the actual sound-data chunk:
                packet = self.compressed_marker(packet, 2, "sound-data")
        # we do want to reformat cursor packets...
        # as they will have been uncompressed by the network layer already:
        elif packet_type == "cursor":
            # packet = ["cursor", "png", x, y, width, height, xhot, yhot, serial, pixels, name]
            # or:
            # packet = ["cursor", ""]
            if len(packet) >= 8:
                packet = self._packet_recompress(packet, 9, "cursor")
        elif packet_type == "window-icon":
            if not isinstance(packet[5], str):
                packet = self._packet_recompress(packet, 5, "icon")
        elif packet_type == "send-file":
            if packet[6]:
                packet = self.compressed_marker(packet, 6, "file-data")
        elif packet_type == "send-file-chunk":
            if packet[3]:
                packet = self.compressed_marker(packet, 3, "file-chunk-data")
        elif packet_type == "challenge":
            password = self.disp_desc.get("password", self.session_options.get("password"))
            log("password from %s / %s = %s", self.disp_desc, self.session_options, password)
            if not password:
                if not PASSTHROUGH_AUTH:
                    self.stop(None, "authentication requested by the server,",
                              "but no password is available for this session")
                # otherwise, just forward it to the client
                self.client_challenge_packet = packet
            else:
                # client may have already responded to the challenge,
                # so we have to handle authentication from this end
                server_salt = strtobytes(packet[1])
                length = len(server_salt)
                digest = str(packet[3])
                salt_digest = "xor"
                if len(packet) >= 5:
                    salt_digest = str(packet[4])
                if salt_digest in ("xor", "des"):
                    self.stop(None, f"server uses legacy salt digest {salt_digest!r}")
                    return
                if salt_digest == "xor":
                    # with xor, we have to match the size
                    if length < 16:
                        raise ValueError(f"server salt is too short: only {length} bytes, minimum is 16")
                    if length > 256:
                        raise ValueError(f"server salt is too long: {length} bytes, maximum is 256")
                else:
                    # other digest, 32 random bytes is enough:
                    length = 32
                client_salt = get_salt(length)
                salt = gendigest(salt_digest, client_salt, server_salt)
                challenge_response = gendigest(digest, password, salt)
                if not challenge_response:
                    log("invalid digest module '%s': %s", digest)
                    self.stop(None, f"server requested {digest!r} digest but it is not supported")
                    return
                log.info("sending %s challenge response", digest)
                self.send_hello(challenge_response, client_salt)
                return
        self.queue_client_packet(packet)
