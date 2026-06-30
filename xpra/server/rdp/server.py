# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.util.env import envint
from xpra.util.thread import start_thread
from xpra.util.str_fn import bytestostr
from xpra.server.subsystem.stub import StubSubsystem
from xpra.net.rdp.const import SecurityProtocol, RDPNegFailure, protocols_str
from xpra.net.rdp.protocol import (
    parse_tpkt, parse_x224_connection_request,
    format_rdp_neg_rsp, format_rdp_neg_failure, build_connection_confirm,
)
from xpra.log import Logger

log = Logger("rdp")

NEGOTIATION_TIMEOUT = envint("XPRA_RDP_NEGOTIATION_TIMEOUT", 10)
# a Connection Request is tiny, anything larger is bogus:
MAX_REQUEST_SIZE = envint("XPRA_RDP_MAX_REQUEST_SIZE", 4096)
READ_SIZE = 4096


def write_all(conn, data: bytes) -> None:
    while data:
        n = conn.write(data)
        if not n:
            raise ConnectionError("connection closed while writing")
        data = data[n:]


class RDPServer(StubSubsystem):
    """
    Handles the initial RDP connection handshake (TPKT + X.224 negotiation).

    This only implements the negotiation phase: it tells the client which
    security protocols the server supports (and can upgrade the connection to
    TLS), but does not implement an RDP session (MCS, licensing, graphics).
    """
    PREFIX = "rdp"

    def handle_rdp_connection(self, conn, data: bytes = b"") -> None:
        if data and data[:2] != b"\x03\x00":
            raise ValueError("packet is not valid RDP")
        log("handle_rdp_connection(%s, %i bytes)", conn, len(data))
        # run the (blocking) negotiation off the connection-handler thread:
        start_thread(self._negotiate, "rdp-negotiate", daemon=True, args=(conn, bytes(data)))

    def _negotiate(self, conn, data: bytes = b"") -> None:
        try:
            self.do_negotiate(conn, data)
        except ValueError as e:
            log.warn("Warning: invalid RDP connection from %s", conn.target)
            log.warn(" %s", e)
        except Exception:
            log("RDP negotiation failed", exc_info=True)
        finally:
            try:
                conn.close()
            except OSError:
                log("error closing %s", conn, exc_info=True)

    def do_negotiate(self, conn, data: bytes = b"") -> None:
        conn.set_timeout(NEGOTIATION_TIMEOUT)
        # read until we have a complete TPKT PDU (the Connection Request):
        buf = data
        while True:
            payload, consumed = parse_tpkt(buf)
            if consumed:
                break
            if len(buf) > MAX_REQUEST_SIZE:
                raise ValueError("RDP connection request is too large")
            chunk = conn.read(READ_SIZE)
            if not chunk:
                log.info("RDP connection from %s closed before negotiation", conn.target)
                return
            buf += chunk
        cr = parse_x224_connection_request(payload)
        log.info("RDP connection from %s", conn.target)
        if cr.cookie:
            log.info(" cookie: %s", bytestostr(cr.cookie))
        if cr.has_negotiation:
            log.info(" requested security: %s", protocols_str(cr.requested_protocols))
        else:
            log.info(" no security negotiation (standard RDP)")
        ssl_options = self.get_ssl_options(conn)
        response, selected = self.negotiation_response(cr, bool(ssl_options.get("cert")))
        write_all(conn, build_connection_confirm(response))
        if selected == SecurityProtocol.SSL:
            self.upgrade_to_tls(conn, ssl_options)
        # we only implement the negotiation handshake, so we stop here:
        log.info(" negotiation complete, closing connection")

    def negotiation_response(self, cr, have_cert: bool) -> tuple[bytes, int]:
        # the only protocol we can actually follow through with is TLS,
        # so we require the client to have offered SSL:
        if cr.requested_protocols & SecurityProtocol.SSL:
            if have_cert:
                log.info(" selecting SSL")
                return format_rdp_neg_rsp(SecurityProtocol.SSL), SecurityProtocol.SSL
            log.info(" rejecting: no SSL certificate available")
            return format_rdp_neg_failure(RDPNegFailure.SSL_CERT_NOT_ON_SERVER), 0
        log.info(" rejecting: SSL is required by this server")
        return format_rdp_neg_failure(RDPNegFailure.SSL_REQUIRED_BY_SERVER), 0

    def get_ssl_options(self, conn) -> dict:
        get_ssl_socket_options = getattr(self.server, "get_ssl_socket_options", None)
        if not get_ssl_socket_options:
            return {}
        try:
            return get_ssl_socket_options(conn.options)
        except Exception:
            log("get_ssl_socket_options(%s) failed", conn.options, exc_info=True)
            return {}

    def upgrade_to_tls(self, conn, ssl_options: dict) -> None:
        from xpra.net.tls.socket import ssl_wrap_socket, ssl_handshake
        raw_sock = conn.get_raw_socket()
        raw_sock.setblocking(True)
        options = dict(ssl_options)
        options["server_side"] = True
        ssl_sock = ssl_wrap_socket(raw_sock, **options)
        if not ssl_sock:
            raise RuntimeError("failed to wrap the socket for TLS")
        ssl_handshake(ssl_sock)
        log.info(" RDP connection upgraded to TLS: %s", ssl_sock.version())
        # we don't implement the RDP session that would follow, so close the TLS layer:
        try:
            ssl_sock.close()
        except OSError:
            log("error closing TLS socket", exc_info=True)
