# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

"""
Register subsystem.

For each `--register=URI` option, opens an authenticated connection to a
proxy server and announces this xpra server with its `uuid`, `session-name`
and `display`. The proxy stores the registration in its `live` session
registry so a client connecting to the proxy can later be brokered to this
server.

The dial loop runs in a background thread per URI and reconnects with
exponential backoff if the connection drops.
"""

import threading
from queue import Queue
from typing import Any

from xpra.net.bytestreams import set_socket_timeout
from xpra.net.common import Packet, FULL_INFO
from xpra.net.connect import connect_to
from xpra.net.digest import get_salt, gendigest, get_caps as get_digest_caps
from xpra.net.net_util import get_network_caps
from xpra.net.packet_type import INFO_RESPONSE
from xpra.net.protocol.socket_handler import SocketProtocol
from xpra.scripts.config import make_defaults_struct
from xpra.scripts.parsing import parse_display_name
from xpra.server.subsystem.stub import StubSubsystem
from xpra.util.str_fn import redact_uri
from xpra.util.thread import start_thread
from xpra.util.version import get_version_info
from xpra.log import Logger

log = Logger("server", "auth")

INITIAL_BACKOFF = 1.0
MAX_BACKOFF = 60.0
CONNECT_TIMEOUT = 30.0


class RegPacketDispatcher:
    """
    Network-thread packet sink for one in-flight registration.

    Until `hand_off()` is called, every packet read from the wire is
    appended to `inbox` for the registration loop to consume in order
    (HMAC challenge, hello ack, ping, etc.). When the proxy signals
    handover, `hand_off()` runs under the same lock the network thread
    uses to dispatch — guaranteeing that:

    1. Any packets already in `inbox` are forwarded to
       `server.process_packet` first, preserving TCP order.
    2. The `handed_off` flag flips after the drain, so subsequent
       network-thread calls go straight to `server.process_packet`
       without ever touching the queue.

    Without the lock, a packet arriving between the drain and the flag
    flip could either get stuck on the queue or be delivered to the
    server out of order.
    """

    def __init__(self, inbox: Queue, server):
        self.inbox = inbox
        self.server = server
        self.handed_off = False
        self.lock = threading.Lock()

    def __call__(self, proto, packet: Packet) -> None:
        with self.lock:
            if self.handed_off:
                self.server.process_packet(proto, packet)
            else:
                self.inbox.put(packet)

    def hand_off(self, proto) -> None:
        with self.lock:
            while not self.inbox.empty():
                self.server.process_packet(proto, self.inbox.get_nowait())
            self.handed_off = True


class RegisterSubsystem(StubSubsystem):
    PREFIX = "register"

    def __init__(self, server):
        super().__init__(server)
        # parsed display descriptors, keyed by the original URI string:
        self._descs: dict[str, dict] = {}
        # protocol-shaping settings captured from opts at init time:
        self._compression_level: int = 1
        self._encoder: str = ""
        self._compressor: str = ""
        self._shutdown = threading.Event()
        self._threads: list[threading.Thread] = []
        # active SocketProtocols by URI so cleanup can close them:
        self._active: dict[str, SocketProtocol] = {}
        self._active_lock = threading.Lock()

    def init(self, opts) -> None:
        super().init(opts)
        self._compression_level = int(opts.compression_level)
        # `packet_encoders` / `compressors` default to ["all"] which means
        # "let the protocol pick its default"; only honour explicit picks.
        encoders = list(opts.packet_encoders or [])
        if encoders and encoders[0] != "all":
            self._encoder = encoders[0]
        compressors = list(opts.compressors or [])
        if compressors and compressors[0] != "all":
            self._compressor = compressors[0]
        # parse URIs once; the result is what we actually need at dial time.
        for uri in opts.register or ():
            try:
                desc = parse_display_name(opts, uri)
            except Exception as e:
                log("parse_display_name(%r) failed", uri, exc_info=True)
                log.warn("Warning: ignoring invalid --register %s: %s", uri, e)
                continue
            self._descs[uri] = desc

    def setup(self) -> None:
        for uri, desc in self._descs.items():
            t = start_thread(self._registration_loop, f"register({uri})", daemon=True, args=(uri, desc))
            self._threads.append(t)

    def cleanup(self) -> None:
        self._shutdown.set()
        with self._active_lock:
            protos = list(self._active.values())
            self._active.clear()
        for proto in protos:
            try:
                proto.close()
            except OSError:
                log("error closing %s during cleanup", proto, exc_info=True)

    def get_info(self, _proto) -> dict[str, Any]:
        def sanitize(uris):
            return [u if FULL_INFO > 1 else redact_uri(u) for u in uris]
        with self._active_lock:
            return {
                "uris": sanitize(self._descs.keys()),
                "active": sanitize(self._active.keys()),
            }

    def _registration_loop(self, uri: str, desc: dict) -> None:
        backoff = INITIAL_BACKOFF
        while not self._shutdown.is_set():
            handed_off = False
            try:
                ok, handed_off = self._attempt_registration(uri, desc)
                if ok:
                    backoff = INITIAL_BACKOFF
                else:
                    log("registration with %r ended without ack", uri)
            except Exception as e:
                log("registration with %r failed", uri, exc_info=True)
                log.warn("Warning: --register %s failed: %s", uri, e)
            if handed_off:
                # the registration was consumed by a client — re-dial
                # immediately so the slot stays warm
                continue
            if self._shutdown.wait(backoff):
                return
            backoff = min(backoff * 2, MAX_BACKOFF)

    def _attempt_registration(self, uri: str, desc: dict) -> tuple[bool, bool]:
        log("register: dialling %r (%s)", uri, desc)
        conn = connect_to(desc, make_defaults_struct())
        if conn is None:
            log.warn("Warning: register failed: cannot connect to %r", uri)
            return False, False
        conn.timeout = CONNECT_TIMEOUT
        password = desc.get("password", "")

        # Inbound packet queue and a small dispatcher that lets us atomically
        # transition the proto from "registration loop reads from inbox" to
        # "server's accept path receives packets directly" — see the
        # `RegPacketDispatcher` docstring for the rationale.
        inbox: Queue = Queue()
        dispatcher = RegPacketDispatcher(inbox, self.server)

        # leave get_packet_cb as the SocketProtocol default (`no_packet`)
        # so that `send_now()` can install its own one-shot source.
        proto = SocketProtocol(conn, dispatcher)
        # the protocol needs a packet encoder + compressor before it can
        # frame outbound packets — without these, `send_now()` writes the
        # raw repr() of the packet and the proxy disconnects on the
        # invalid packet header. Mirrors `xpra.client.base.client`.
        proto.set_compression_level(self._compression_level)
        if self._encoder:
            proto.enable_encoder(self._encoder)
        else:
            proto.enable_default_encoder()
        if self._compressor:
            proto.enable_compressor(self._compressor)
        else:
            proto.enable_default_compressor()
        with self._active_lock:
            self._active[uri] = proto
        proto.large_packets.append(INFO_RESPONSE)
        handed_off = False
        try:
            proto.start()
            self._send_hello(proto, password)
            ack, handed_off = self._handle_registration_packets(proto, dispatcher, password, inbox)
            return ack, handed_off
        finally:
            with self._active_lock:
                self._active.pop(uri, None)
            if not handed_off:
                try:
                    proto.close()
                except OSError:
                    pass

    def _handle_registration_packets(self, proto: SocketProtocol,
                                     dispatcher: RegPacketDispatcher,
                                     password: str, inbox: Queue) -> tuple[bool, bool]:
        """
        Returns (ack_received, handed_off).
        `handed_off` is True when a `handover` packet has transferred
        ownership of `proto` to the server's accept loop; in that case the
        caller must NOT close the protocol.
        """
        ack_received = False
        # block until a packet arrives or the server is shutting down
        while not self._shutdown.is_set():
            try:
                packet = inbox.get(timeout=1.0)
            except Exception:
                continue
            ptype = packet.get_type()
            log("register: received %r", ptype)
            if ptype == "challenge":
                self._handle_challenge(proto, password, packet)
                continue
            if ptype == "hello":
                if not ack_received:
                    log.info("registered with %s", getattr(proto._conn, "target", proto))
                    # the registration is steady-state from here; clear the
                    # connect-time read timeout so the socket can sit idle
                    # waiting for a handover without the read loop dying.
                    # Mirrors what the proxy's accept_connection() does on
                    # its side of the same TCP connection.
                    set_socket_timeout(proto._conn, None)
                    ack_received = True
                continue
            if ptype == "handover":
                # The proxy is about to splice a client onto this socket.
                # `dispatcher.hand_off()` atomically drains anything still
                # on the inbox to the server (preserving TCP order) and
                # flips the dispatcher so subsequent packets go straight to
                # the server. `_adopt_for_server` then registers the proto
                # with the server's accept loop so the next hello it sees
                # is processed as a fresh inbound client.
                dispatcher.hand_off(proto)
                self._adopt_for_server(proto)
                return True, True
            if ptype in ("disconnect", "connection-lost"):
                log("register: peer disconnected (%s)", packet)
                return ack_received, False
            # everything else is ignored
        return ack_received, False

    def _adopt_for_server(self, proto: SocketProtocol) -> None:
        """
        Re-purpose the registration protocol as a normal inbound client
        connection from the server's perspective. The proxy keeps the
        socket alive and will forward a filtered client hello next. Packet
        routing has already been swapped by the `RegPacketDispatcher`
        — this method only takes care of the bookkeeping the server's
        accept code depends on.
        """
        srv = self.server
        try:
            if proto not in srv._potential_protocols:
                srv._potential_protocols.append(proto)
            srv.schedule_verify_connection_accepted(proto, srv._accept_timeout)
            log.info("registration with %s handed off to local server",
                     getattr(proto._conn, "target", proto))
        except Exception as e:
            log("error handing off %s", proto, exc_info=True)
            log.warn("Warning: failed to adopt registration connection: %s", e)
            try:
                proto.close()
            except OSError:
                pass

    def _handle_challenge(self, proto: SocketProtocol, password: str, packet: Packet) -> None:
        if not password:
            log.warn("Warning: register challenge received but no password set in URI")
            proto.close()
            return
        server_salt = packet.get_bytes(1)
        digest = packet.get_str(3)
        actual_digest = digest.split(":", 1)[0]
        salt_digest = "xor"
        if len(packet) >= 5:
            salt_digest = packet.get_str(4)
        length = len(server_salt) if salt_digest == "xor" else 32
        client_salt = get_salt(length)
        salt = gendigest(salt_digest, client_salt, server_salt)
        response = gendigest(actual_digest, password, salt)
        log("register: responding to %s challenge", actual_digest)
        self._send_hello(proto, password, challenge_response=response, client_salt=client_salt)

    def _send_hello(self, proto: SocketProtocol, password: str,
                    challenge_response=b"", client_salt=b"") -> None:
        hello = self.make_proxy_hello()
        if password and not challenge_response:
            hello["challenge"] = True
        if challenge_response:
            hello["challenge_response"] = challenge_response
            if client_salt:
                hello["challenge_client_salt"] = client_salt
        log("register: sending hello %s", hello)
        proto.send_now(Packet("hello", hello))

    def make_proxy_hello(self) -> dict[str, Any]:
        srv = self.server
        id_sub = srv.subsystems.get("id")
        uuid = getattr(id_sub, "uuid", "")
        session_name = getattr(srv, "session_name", "") or ""
        try:
            display = srv.get_display_name() or ""
        except AttributeError:
            display = ""
        # the proxy negotiates the encoder/compressor by inspecting our
        # `encoders`/`compressors` caps, and it may also issue an HMAC
        # challenge — include both. We deliberately do NOT include the
        # full server make_hello caps here; those are produced fresh
        # against the actual client at brokering time.
        hello: dict[str, Any] = {
            "request": "register",
            "uuid": uuid,
            "session-name": session_name,
            "display": display,
            "displays": [display] if display else [],
            "username": "",
            "client_type": "xpra-register",
        }
        hello.update(get_version_info(0))
        hello.update(get_network_caps())
        hello.update(get_digest_caps())
        return hello
