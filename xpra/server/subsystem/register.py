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
server (the brokering is phase 3b — phase 3a stops once the proxy
acknowledges the registration).

The dial loop runs in a background thread per URI and reconnects with
exponential backoff if the connection drops.
"""

import threading
from queue import Queue
from typing import Any

from xpra.net.common import Packet
from xpra.net.connect import connect_to
from xpra.net.digest import get_salt, gendigest
from xpra.net.protocol.socket_handler import SocketProtocol
from xpra.scripts.parsing import parse_display_name
from xpra.server.subsystem.stub import StubSubsystem
from xpra.util.thread import start_thread
from xpra.log import Logger

log = Logger("server", "auth")

INITIAL_BACKOFF = 1.0
MAX_BACKOFF = 60.0
CONNECT_TIMEOUT = 30.0


class RegisterSubsystem(StubSubsystem):
    PREFIX = "register"

    def __init__(self, server):
        super().__init__(server)
        self.uris: list[str] = []
        self._shutdown = threading.Event()
        self._threads: list[threading.Thread] = []
        # active SocketProtocols by URI so cleanup can close them:
        self._active: dict[str, SocketProtocol] = {}
        self._active_lock = threading.Lock()

    def init(self, opts) -> None:
        super().init(opts)
        self.uris = list(getattr(opts, "register", None) or [])
        self._opts = opts

    def setup(self) -> None:
        for uri in self.uris:
            t = start_thread(self._registration_loop, f"register({uri})", daemon=True, args=(uri,))
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
        with self._active_lock:
            return {
                "uris": list(self.uris),
                "active": list(self._active.keys()),
            }

    def _registration_loop(self, uri: str) -> None:
        backoff = INITIAL_BACKOFF
        while not self._shutdown.is_set():
            try:
                ok = self._attempt_registration(uri)
                if ok:
                    backoff = INITIAL_BACKOFF
                else:
                    log("registration with %r ended without ack", uri)
            except Exception as e:
                log("registration with %r failed", uri, exc_info=True)
                log.warn("Warning: --register %s failed: %s", uri, e)
            if self._shutdown.wait(backoff):
                return
            backoff = min(backoff * 2, MAX_BACKOFF)

    def _attempt_registration(self, uri: str) -> bool:
        desc = parse_display_name(self._opts, uri)
        log("register: parsed %r -> %s", uri, desc)
        conn = connect_to(desc, self._opts)
        if conn is None:
            log.warn("Warning: register failed: cannot connect to %r", uri)
            return False
        conn.timeout = CONNECT_TIMEOUT
        password = desc.get("password", "")

        # Inbound packet queue: the SocketProtocol calls process_packet_cb
        # from its network thread; the dial-loop thread reads from this queue.
        inbox: Queue = Queue()

        def process_packet(_proto, packet: Packet) -> None:
            inbox.put(packet)

        # leave get_packet_cb as the SocketProtocol default (`no_packet`)
        # so that `send_now()` can install its own one-shot source.
        proto = SocketProtocol(conn, process_packet)
        with self._active_lock:
            self._active[uri] = proto
        try:
            proto.start()
            self._send_hello(proto, password, challenge_response=b"", client_salt=b"")
            return self._handle_registration_packets(proto, password, inbox)
        finally:
            with self._active_lock:
                self._active.pop(uri, None)
            try:
                proto.close()
            except OSError:
                pass

    def _handle_registration_packets(self, proto: SocketProtocol, password: str, inbox: Queue) -> bool:
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
                    ack_received = True
                continue
            if ptype in ("disconnect", "connection-lost"):
                log("register: peer disconnected (%s)", packet)
                return ack_received
            # everything else is ignored — phase 3a is passive
        return ack_received

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
                    challenge_response: bytes, client_salt: bytes) -> None:
        hello = self._build_hello()
        if password and not challenge_response:
            hello["challenge"] = True
        if challenge_response:
            hello["challenge_response"] = challenge_response
            if client_salt:
                hello["challenge_client_salt"] = client_salt
        log("register: sending hello %s", hello)
        proto.send_now(Packet("hello", hello))

    def _build_hello(self) -> dict[str, Any]:
        srv = self.server
        id_sub = srv.subsystems.get("id")
        uuid = getattr(id_sub, "uuid", "") if id_sub else ""
        session_name = getattr(srv, "session_name", "") or ""
        try:
            display = srv.get_display_name() or ""
        except AttributeError:
            display = ""
        username = ""
        return {
            "request": "register",
            "version": "",
            "uuid": uuid,
            "session-name": session_name,
            "display": display,
            "displays": [display] if display else [],
            "username": username,
            "client_type": "xpra-register",
        }


# Public symbol name used by `add_subsystem`:
ServerSubsystem = RegisterSubsystem
