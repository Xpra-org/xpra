#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2024 Antoine Martin <antoine@xpra.org>
# Copyright (C) 2026 Netflix, Inc.
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import asyncio
import datetime
import os
import socket
import tempfile
import unittest
from unittest.mock import MagicMock, patch
from time import time, sleep

try:
    import aioquic
    HAVE_AIOQUIC = bool(aioquic)
except ImportError:
    HAVE_AIOQUIC = False


def _make_protocol(xpra_server=None):
    """Create an HttpServerProtocol bypassing QuicConnectionProtocol.__init__."""
    from xpra.net.quic.listener import HttpServerProtocol
    protocol = HttpServerProtocol.__new__(HttpServerProtocol)
    protocol._xpra_server = xpra_server or MagicMock()
    protocol.http_origin = "auto"
    protocol._handlers = {}
    protocol._http = None
    protocol._quic = MagicMock()
    protocol._transport = MagicMock()
    protocol._transport.get_extra_info = lambda k: None
    protocol.transmit = MagicMock()
    return protocol


@unittest.skipUnless(HAVE_AIOQUIC, "aioquic not available")
class TestHttpServerProtocolInit(unittest.TestCase):

    def test_default_state(self):
        p = _make_protocol()
        assert p._handlers == {}
        assert p._http is None

    def test_xpra_server_stored(self):
        server = MagicMock()
        p = _make_protocol(xpra_server=server)
        assert p._xpra_server is server


@unittest.skipUnless(HAVE_AIOQUIC, "aioquic not available")
class TestHttpServerProtocolEvents(unittest.TestCase):

    def test_quic_event_datagram_quack(self):
        from aioquic.quic.events import DatagramFrameReceived
        p = _make_protocol()
        event = MagicMock(spec=DatagramFrameReceived)
        event.data = b"quack"
        # _http is None so the event loop won't try to dispatch to http
        p.quic_event_received(event)
        p._quic.send_datagram_frame.assert_called_once_with(b"quack-ack")

    def test_quic_event_protocol_negotiated_h3(self):
        from aioquic.h3.connection import H3_ALPN
        from aioquic.quic.events import ProtocolNegotiated
        p = _make_protocol()
        event = MagicMock(spec=ProtocolNegotiated)
        event.alpn_protocol = H3_ALPN[0]
        # H3Connection requires a real quic object; swallow any TypeError
        try:
            p.quic_event_received(event)
        except Exception:
            pass

    def test_quic_event_protocol_negotiated_h0(self):
        from aioquic.h0.connection import H0_ALPN
        from aioquic.quic.events import ProtocolNegotiated
        p = _make_protocol()
        event = MagicMock(spec=ProtocolNegotiated)
        event.alpn_protocol = H0_ALPN[0]
        try:
            p.quic_event_received(event)
        except Exception:
            pass


@unittest.skipUnless(HAVE_AIOQUIC, "aioquic not available")
class TestNewHttpHandler(unittest.TestCase):

    def _make_protocol_with_http(self):
        p = _make_protocol()
        p._http = MagicMock()
        p._http._quic = MagicMock()
        p._http._quic._network_paths = [MagicMock(addr=("127.0.0.1", 9999))]
        return p

    def _make_headers_event(self, method, path, protocol=None, extra=()):
        event = MagicMock()
        event.stream_id = 1
        headers = [
            (b":method", method.encode()),
            (b":path", path.encode()),
            (b":authority", b"localhost"),
        ]
        if protocol:
            headers.append((b":protocol", protocol.encode()))
        headers.extend(extra)
        event.headers = headers
        return event

    def test_websocket_handler(self):
        from xpra.net.quic.websocket import ServerWebSocketConnection
        p = self._make_protocol_with_http()
        event = self._make_headers_event("CONNECT", "/", protocol="websocket")
        handler = p.new_http_handler(event)
        assert isinstance(handler, ServerWebSocketConnection)
        assert p._xpra_server.make_protocol.called

    def test_websocket_same_origin(self):
        from xpra.net.quic.websocket import ServerWebSocketConnection
        p = self._make_protocol_with_http()
        event = self._make_headers_event(
            "CONNECT", "/", protocol="websocket",
            extra=[(b"origin", b"https://localhost")],
        )
        handler = p.new_http_handler(event)
        assert isinstance(handler, ServerWebSocketConnection)
        assert p._xpra_server.make_protocol.called

    def test_websocket_cross_origin(self):
        p = self._make_protocol_with_http()
        event = self._make_headers_event(
            "CONNECT", "/", protocol="websocket",
            extra=[(b"origin", b"https://evil.example")],
        )
        handler = p.new_http_handler(event)
        assert handler is None
        p._http.send_headers.assert_called_once_with(
            stream_id=event.stream_id,
            headers=[(b":status", b"403")],
            end_stream=True,
        )
        p.transmit.assert_called_once()
        p._xpra_server.make_protocol.assert_not_called()

    def test_webtransport_handler(self):
        from xpra.net.quic.webtransport import ServerWebTransportConnection
        p = self._make_protocol_with_http()
        event = self._make_headers_event("CONNECT", "/wt", protocol="webtransport")
        handler = p.new_http_handler(event)
        assert isinstance(handler, ServerWebTransportConnection)
        assert p._xpra_server.make_protocol.called

    def test_http_get_handler(self):
        from xpra.net.quic.http import HttpRequestHandler
        p = self._make_protocol_with_http()
        event = self._make_headers_event("GET", "/index.html")
        handler = p.new_http_handler(event)
        assert isinstance(handler, HttpRequestHandler)

    def test_query_string_split(self):
        from xpra.net.quic.http import HttpRequestHandler
        p = self._make_protocol_with_http()
        event = self._make_headers_event("GET", "/page?foo=bar")
        handler = p.new_http_handler(event)
        assert isinstance(handler, HttpRequestHandler)
        assert handler.scope.get("query_string") == b"foo=bar"

    def test_non_colon_headers_forwarded(self):
        from xpra.net.quic.http import HttpRequestHandler
        p = self._make_protocol_with_http()
        event = self._make_headers_event(
            "GET", "/",
            extra=[(b"x-custom-header", b"value123")],
        )
        handler = p.new_http_handler(event)
        assert isinstance(handler, HttpRequestHandler)
        headers = handler.scope.get("headers", [])
        assert any(h[0] == b"x-custom-header" for h in headers)


@unittest.skipUnless(HAVE_AIOQUIC, "aioquic not available")
class TestDoListen(unittest.TestCase):

    def test_bad_cert_returns_none(self):
        from xpra.net.quic.listener import do_listen
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.bind(("127.0.0.1", 0))
        try:
            result = asyncio.run(do_listen(sock, MagicMock(), "/nonexistent/cert.pem", None, False))
            assert result is None
        finally:
            sock.close()

    def test_bad_key_returns_none(self):
        from xpra.net.quic.listener import do_listen
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.bind(("127.0.0.1", 0))
        try:
            result = asyncio.run(do_listen(sock, MagicMock(), "/no/cert.pem", "/no/key.pem", False))
            assert result is None
        finally:
            sock.close()


@unittest.skipUnless(HAVE_AIOQUIC, "aioquic not available")
class TestListenQuic(unittest.TestCase):

    def test_missing_cert_raises_init_exit(self):
        from xpra.net.quic.listener import listen_quic
        from xpra.scripts.config import InitExit
        server = MagicMock()
        server.get_ssl_socket_options = lambda opts: {}
        # find_ssl_cert is imported lazily inside listen_quic; patch it at its source
        with patch("xpra.net.tls.file.find_ssl_cert", return_value=""):
            with self.assertRaises(InitExit):
                listen_quic(MagicMock(), server, {})

    def test_missing_key_raises_init_exit(self):
        from xpra.net.quic.listener import listen_quic
        from xpra.scripts.config import InitExit
        server = MagicMock()
        # cert is set via socket options, key comes from find_ssl_cert which returns ""
        server.get_ssl_socket_options = lambda opts: {"cert": "/some/cert.pem"}
        with patch("xpra.net.tls.file.find_ssl_cert", return_value=""):
            with self.assertRaises(InitExit):
                listen_quic(MagicMock(), server, {})


def _make_key_and_cert(common_name: str, not_after_days: int = 30, signing_key=None):
    """Return (key_pem, cert_pem) for a throwaway self-signed certificate.

    Pass signing_key= to sign with an existing key (used for the
    same-key-new-cert renewal case)."""
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID
    key = signing_key or ec.generate_private_key(ec.SECP256R1())
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, common_name)])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(now + datetime.timedelta(days=not_after_days))
        .sign(key, hashes.SHA256())
    )
    key_pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    cert_pem = cert.public_bytes(serialization.Encoding.PEM)
    return key_pem, cert_pem


class ImmediateLoop:
    """Stand-in for an asyncio loop that runs call_soon_threadsafe inline."""

    def __init__(self):
        self.calls = []

    def call_soon_threadsafe(self, callback, *args):
        self.calls.append(callback)
        callback(*args)


class DeadLoop:
    def call_soon_threadsafe(self, callback, *args):
        raise RuntimeError("event loop is closed")


class SleepingLoop:
    """Never runs callbacks on its own; stores them so tests can flush later
    and prove a timed-out swap still applies."""

    def __init__(self):
        self.pending = []

    def call_soon_threadsafe(self, callback, *args):
        self.pending.append((callback, args))


@unittest.skipUnless(HAVE_AIOQUIC, "aioquic not available")
class TestValidateCertificateFiles(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        self.key_a_pem, self.cert_a_pem = _make_key_and_cert("validate-a")
        self.key_b_pem, self.cert_b_pem = _make_key_and_cert("validate-b")
        self.cert_path = os.path.join(self.tmpdir.name, "cert.pem")
        self.key_path = os.path.join(self.tmpdir.name, "key.pem")

    def _write(self, cert_data, key_data):
        for path, data in ((self.cert_path, cert_data), (self.key_path, key_data)):
            with open(path, "wb") as f:
                f.write(data)

    def _validate(self):
        from xpra.net.quic.listener import validate_certificate_files
        return validate_certificate_files(self.cert_path, self.key_path)

    def test_good_files_validate(self):
        self._write(self.cert_a_pem, self.key_a_pem)
        certificate, chain, private_key = self._validate()
        assert chain == []
        assert private_key is not None
        assert certificate.serial_number is not None

    def test_validate_same_key_new_cert(self):
        # the acme.sh renewal case: new cert signed by the same private key
        from cryptography.hazmat.primitives import serialization
        key_a = serialization.load_pem_private_key(self.key_a_pem, password=None)
        _, cert_b_pem = _make_key_and_cert("validate-a-renewed", signing_key=key_a)
        self._write(cert_b_pem, self.key_a_pem)
        certificate, _, _ = self._validate()
        assert certificate.serial_number is not None

    def test_validate_corrupt_cert(self):
        self._write(b"this is not a certificate", self.key_a_pem)
        with self.assertRaises(ValueError) as raised:
            self._validate()
        assert self.cert_path in str(raised.exception)

    def test_validate_missing_file(self):
        with self.assertRaises(ValueError) as raised:
            self._validate()
        assert self.cert_path in str(raised.exception)

    def test_validate_key_mismatch(self):
        # cert B on disk, key A on disk: the out-of-sync renewal failure mode
        self._write(self.cert_b_pem, self.key_a_pem)
        with self.assertRaises(ValueError) as raised:
            self._validate()
        assert "does not match" in str(raised.exception)

    def test_validate_corrupt_key(self):
        # valid cert with a garbage key file pins the validate-first order:
        # aioquic assigns the certificate before reading the key, so loading
        # straight into the live configuration would corrupt it right here
        self._write(self.cert_b_pem, b"not a private key")
        with self.assertRaises(ValueError) as raised:
            self._validate()
        assert self.key_path in str(raised.exception)


@unittest.skipUnless(HAVE_AIOQUIC, "aioquic not available")
class TestApplyQuicCertificate(unittest.TestCase):

    def setUp(self):
        from aioquic.quic.configuration import QuicConfiguration
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        key_pem, cert_pem = _make_key_and_cert("apply-a")
        self.cert_path = os.path.join(self.tmpdir.name, "cert.pem")
        self.key_path = os.path.join(self.tmpdir.name, "key.pem")
        for path, data in ((self.cert_path, cert_pem), (self.key_path, key_pem)):
            with open(path, "wb") as f:
                f.write(data)
        self.configuration = QuicConfiguration(is_client=False)
        self.configuration.load_cert_chain(self.cert_path, self.key_path)
        self.old_serial = self.configuration.certificate.serial_number
        self.key_a_pem = key_pem
        self.new_certificate, self.new_chain, self.new_private_key = \
            self._write_b_and_validate()
        self.ticket_store = self._make_store_with_ticket()

    def _validated_tuple(self):
        from xpra.net.quic.listener import validate_certificate_files
        return validate_certificate_files(self.cert_path, self.key_path)

    def _make_store_with_ticket(self):
        from xpra.net.quic.session_ticket_store import SessionTicketStore
        from aioquic.tls import SessionTicket, CipherSuite
        store = SessionTicketStore()
        now = datetime.datetime.now(datetime.timezone.utc)
        store.add(SessionTicket(
            age_add=0,
            cipher_suite=CipherSuite.AES_128_GCM_SHA256,
            not_valid_before=now,
            not_valid_after=now + datetime.timedelta(days=1),
            resumption_secret=b"x" * 32,
            server_name="localhost",
            ticket=b"old-ticket",
        ))
        return store

    def _write_b_and_validate(self):
        """Write a second cert/key pair over the paths, then validate it.

        setUp already loaded the live configuration from cert A, so the
        validated tuple must come from cert B for the swap to be observable."""
        key_b_pem, cert_b_pem = _make_key_and_cert("apply-b")
        for path, data in ((self.cert_path, cert_b_pem), (self.key_path, key_b_pem)):
            with open(path, "wb") as f:
                f.write(data)
        return self._validated_tuple()

    def _apply(self, loop, timeout=10):
        return self._apply_with(
            self.new_certificate, self.new_chain, self.new_private_key,
            loop, timeout=timeout)

    def test_apply_swaps_and_clears_ticket_store(self):
        summary = self._apply(ImmediateLoop())
        assert self.configuration.certificate.serial_number != self.old_serial
        assert self.configuration.certificate_chain == self.new_chain
        assert self.configuration.private_key == self.new_private_key
        assert self.ticket_store.tickets == {}
        assert "notAfter" in summary

    def test_apply_dead_loop_raises(self):
        with self.assertRaises(ValueError):
            self._apply(DeadLoop())
        # nothing was swapped:
        assert self.configuration.certificate.serial_number == self.old_serial

    def test_apply_timeout_reports_failure(self):
        loop = SleepingLoop()
        with self.assertRaises(ValueError) as raised:
            self._apply(loop, timeout=0.2)
        assert "may still be applied" in str(raised.exception)
        assert self.configuration.certificate.serial_number == self.old_serial
        # the queued swap of already-validated material still applies once
        # the loop runs it — specified behavior, disclosed in the error:
        for callback, args in loop.pending:
            callback(*args)
        assert self.configuration.certificate.serial_number != self.old_serial
        assert self.ticket_store.tickets == {}

    def test_apply_same_key_renewal(self):
        # the acme.sh case at the apply level: new cert signed by the same key
        from cryptography.hazmat.primitives import serialization
        key_a = serialization.load_pem_private_key(self.key_a_pem, password=None)
        _, cert_c_pem = _make_key_and_cert("apply-a-renewed", signing_key=key_a)
        # setUp overwrote the key file with key B; put key A back so cert C
        # (signed by key A) validates against it
        with open(self.cert_path, "wb") as f:
            f.write(cert_c_pem)
        with open(self.key_path, "wb") as f:
            f.write(self.key_a_pem)
        certificate, chain, private_key = self._validated_tuple()
        summary = self._apply_with(certificate, chain, private_key, ImmediateLoop())
        assert self.configuration.certificate.serial_number != self.old_serial
        assert "notAfter" in summary

    def _apply_with(self, certificate, chain, private_key, loop, timeout=10):
        from xpra.net.quic.listener import apply_quic_certificate
        return apply_quic_certificate(
            self.configuration,
            certificate, chain, private_key,
            self.ticket_store, loop, self.cert_path, timeout=timeout,
        )


@unittest.skipUnless(HAVE_AIOQUIC, "aioquic not available")
class TestListenQuicRegistration(unittest.TestCase):

    def _cert_files(self, name):
        key_pem, cert_pem = _make_key_and_cert(name)
        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        cert_path = os.path.join(tmpdir.name, "cert.pem")
        key_path = os.path.join(tmpdir.name, "key.pem")
        for path, data in ((cert_path, cert_pem), (key_path, key_pem)):
            with open(path, "wb") as f:
                f.write(data)
        return cert_path, key_path

    def _wait_for(self, predicate, timeout=5.0):
        deadline = time() + timeout
        while time() < deadline:
            if predicate():
                return True
            sleep(0.05)
        return False

    def test_listen_registers_and_cleanup_unregisters(self):
        from xpra.net.quic.listener import listen_quic
        cert_path, key_path = self._cert_files("listen-registration")
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.bind(("127.0.0.1", 0))
        self.addCleanup(sock.close)
        server = MagicMock()
        server.get_ssl_socket_options = lambda opts: {"cert": cert_path, "key": key_path}
        cleanup = listen_quic(sock, server, {})
        self.addCleanup(cleanup)
        assert self._wait_for(lambda: server.add_quic_configuration.called), \
            "add_quic_configuration was not called"
        cert_arg, key_arg, configuration, ticket_store, loop = \
            server.add_quic_configuration.call_args[0]
        assert cert_arg == cert_path
        assert key_arg == key_path
        from aioquic.quic.configuration import QuicConfiguration
        from xpra.net.quic.session_ticket_store import SessionTicketStore
        assert isinstance(configuration, QuicConfiguration)
        assert isinstance(ticket_store, SessionTicketStore)
        assert loop is not None
        cleanup()
        assert self._wait_for(lambda: server.remove_quic_configuration.called), \
            "remove_quic_configuration was not called"
        server.remove_quic_configuration.assert_called_once_with(configuration)

    def test_cleanup_before_start_never_registers(self):
        import threading
        from xpra.net.quic import listener as quic_listener
        from xpra.net.quic.listener import listen_quic
        cert_path, key_path = self._cert_files("listen-race")
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.bind(("127.0.0.1", 0))
        self.addCleanup(sock.close)
        server = MagicMock()
        server.get_ssl_socket_options = lambda opts: {"cert": cert_path, "key": key_path}
        # track when the listener's do_listen completes, so the test fails
        # (not passes vacuously) if startup never settles on the threaded loop
        real_do_listen = quic_listener.do_listen
        settled = threading.Event()

        async def tracked_do_listen(*args, **kwargs):
            result = await real_do_listen(*args, **kwargs)
            # signal only after the whole listener task step has run: a
            # call_soon callback fires after start_listener's post-await
            # continuation (endpoint assignment, closing check, register or
            # close_endpoint) completes, so the assert cannot race it
            asyncio.get_running_loop().call_soon(settled.set)
            return result

        # the patch must stay active while start_listener runs on the
        # threaded loop, so it covers the whole body:
        with patch("xpra.net.quic.listener.do_listen", tracked_do_listen):
            cleanup = listen_quic(sock, server, {})
            self.addCleanup(cleanup)
            # invoke cleanup now, before startup settles: the registration check
            # runs after the loop has settled either way, so a closing flag set
            # before start_listener's registration step must leave nothing
            # registered (and nothing to unregister)
            cleanup()
            # whichever order the loop races — close_endpoint before
            # start_listener's first step (nothing registered, nothing removed)
            # or after do_listen completed (registered, then unregistered) — a
            # registered entry must never outlive the cleanup:
            assert settled.wait(timeout=5), "listener startup never settled"
            if server.add_quic_configuration.called:
                # registration won the race: the queued close_endpoint must
                # match it with an unregistration before we assert
                assert self._wait_for(lambda: server.remove_quic_configuration.called), \
                    "registered listener was never unregistered"
            assert server.add_quic_configuration.called == \
                server.remove_quic_configuration.called


def main():
    unittest.main()


if __name__ == "__main__":
    main()
