#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Jeremy Lainé
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import asyncio
import importlib.util
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

try:
    from xpra.net.quic import common
    HAVE_AIOQUIC = bool(common)
except ImportError:
    HAVE_AIOQUIC = False


def terminated(error_code: int, reason_phrase: str = ""):
    from aioquic.quic.events import ConnectionTerminated
    return ConnectionTerminated(error_code=error_code, frame_type=None, reason_phrase=reason_phrase)


@unittest.skipUnless(HAVE_AIOQUIC, "aioquic not available")
class AioquicVersionTest(unittest.TestCase):

    def load_common(self, version: str) -> None:
        # a separate copy, so that the module everything else uses is not modified:
        spec = importlib.util.spec_from_file_location("quic_common_copy", common.__file__)
        module = importlib.util.module_from_spec(spec)
        with patch("aioquic.__version__", version):
            spec.loader.exec_module(module)

    def test_too_old(self):
        for version in ("1.2.0", "1.8.0"):
            with self.subTest(version=version):
                with self.assertRaises(ImportError) as cm:
                    self.load_common(version)
                assert f"aioquic {version} is too old" in str(cm.exception)

    def test_supported(self):
        for version in ("1.9.0", "1.10.1"):
            with self.subTest(version=version):
                self.load_common(version)


@unittest.skipUnless(HAVE_AIOQUIC, "aioquic not available")
class ConnectionTerminatedTest(unittest.TestCase):

    def test_recorded(self):
        from aioquic.h3.connection import H3_ALPN
        from aioquic.quic.configuration import QuicConfiguration
        from aioquic.quic.connection import QuicConnection
        from aioquic.quic.events import ProtocolNegotiated
        from aioquic.quic.packet import QuicErrorCode
        from xpra.net.quic.client import WebSocketClient, WebTransportClient
        from xpra.net.quic.common import MAX_DATAGRAM_FRAME_SIZE
        from xpra.net.quic.listener import HttpServerProtocol

        async def check() -> None:
            # the subclasses must call `XpraQuicConnectionProtocol.quic_event_received`:
            for protocol_class in (WebSocketClient, WebTransportClient, HttpServerProtocol):
                with self.subTest(protocol=protocol_class.__name__):
                    configuration = QuicConfiguration(alpn_protocols=H3_ALPN, max_datagram_frame_size=MAX_DATAGRAM_FRAME_SIZE)
                    protocol = protocol_class(QuicConnection(configuration=configuration))
                    assert protocol.connection_terminated is None
                    protocol.quic_event_received(ProtocolNegotiated(alpn_protocol=H3_ALPN[0]))
                    assert protocol.connection_terminated is None
                    event = terminated(QuicErrorCode.PROTOCOL_VIOLATION, "test")
                    protocol.quic_event_received(event)
                    assert protocol.connection_terminated is event

        asyncio.run(check())


@unittest.skipUnless(HAVE_AIOQUIC, "aioquic not available")
class WatchHandshakeTest(unittest.TestCase):

    def watch(self, wait_connected: AsyncMock, connection_terminated=None) -> MagicMock:
        from xpra.net.quic.client import _watch_handshake
        protocol = MagicMock()
        protocol.wait_connected = wait_connected
        protocol.connection_terminated = connection_terminated
        conn = MagicMock()
        asyncio.run(_watch_handshake(protocol, conn, 1))
        return conn

    def test_connected(self):
        conn = self.watch(AsyncMock(return_value=None))
        conn.handshake_failed.assert_not_called()

    def test_certificate_error(self):
        from aioquic.quic.packet import QuicErrorCode
        from xpra.exit_codes import ExitCode
        conn = self.watch(AsyncMock(side_effect=ConnectionError),
                          terminated(QuicErrorCode.CRYPTO_ERROR + 42, "certificate verify failed"))
        conn.handshake_failed.assert_called_once_with(ExitCode.SSL_CERTIFICATE_VERIFY_FAILURE, "certificate verify failed")

    def test_connection_error(self):
        from aioquic.quic.packet import QuicErrorCode
        from xpra.exit_codes import ExitCode
        conn = self.watch(AsyncMock(side_effect=ConnectionError), terminated(QuicErrorCode.PROTOCOL_VIOLATION))
        conn.handshake_failed.assert_called_once_with(ExitCode.CONNECTION_FAILED, "QUIC connection closed with error 0xa")

    def test_timeout(self):
        from xpra.exit_codes import ExitCode
        conn = self.watch(AsyncMock(side_effect=TimeoutError))
        conn.handshake_failed.assert_called_once_with(ExitCode.CONNECTION_FAILED, "QUIC handshake timed out")


@unittest.skipUnless(HAVE_AIOQUIC, "aioquic not available")
class FailedConnectTest(unittest.TestCase):

    def connect(self, connection_terminated) -> None:
        import socket
        from xpra.net.quic import client

        class FailingProtocol(asyncio.DatagramProtocol):
            def connection_made(self, transport) -> None:
                self.transport = transport

            def connect(self, addr, transmit=True) -> None:
                pass

            async def wait_connected(self) -> None:
                # like aioquic, a bare `ConnectionError` once the connection is terminated:
                self.connection_terminated = connection_terminated
                self.transport.close()
                raise ConnectionError

        class ThreadedLoop:
            """ runs everything in the calling thread """
            def sync(self, f, *args):
                async def run():
                    self.loop = asyncio.get_running_loop()
                    return await f(*args)
                return asyncio.run(run())

        async def get_address_options(host: str, port: int) -> tuple:
            return ((socket.AF_INET, socket.SOCK_DGRAM, 0, "", (host, port)), )

        with patch.object(client, "get_threaded_loop", return_value=ThreadedLoop()), \
                patch.object(client, "get_address_options", get_address_options):
            client._quic_connect(FailingProtocol, "127.0.0.1", 9, "/", False)

    def test_certificate_error(self):
        from aioquic.quic.packet import QuicErrorCode
        from xpra.scripts.config import InitExit
        with self.assertRaises(InitExit) as cm:
            self.connect(terminated(QuicErrorCode.CRYPTO_ERROR + 42, "certificate verify failed"))
        assert "certificate verify failed" in str(cm.exception)

    def test_connection_error(self):
        from aioquic.quic.packet import QuicErrorCode
        with self.assertRaises(RuntimeError) as cm:
            self.connect(terminated(QuicErrorCode.PROTOCOL_VIOLATION, "protocol violation"))
        assert str(cm.exception) == "protocol violation"


@unittest.skipUnless(HAVE_AIOQUIC, "aioquic not available")
class WebTransportWithoutDatagramsTest(unittest.TestCase):

    def test_client_protocol(self):
        from aioquic.h3.connection import H3_ALPN
        from aioquic.quic.configuration import QuicConfiguration
        from aioquic.quic.connection import QuicConnection
        from xpra.net.quic.client import WebTransportClient
        # aioquic refuses to enable webtransport without datagrams:
        configuration = QuicConfiguration(alpn_protocols=H3_ALPN, max_datagram_frame_size=None)

        async def check() -> None:
            WebTransportClient(QuicConnection(configuration=configuration))

        asyncio.run(check())

    def test_connect(self):
        from xpra.scripts.config import InitExit
        from xpra.exit_codes import ExitCode
        from xpra.net.quic import client
        with patch.object(client, "MAX_DATAGRAM_FRAME_SIZE", 0):
            with self.assertRaises(InitExit) as cm:
                client.quic_connect("127.0.0.1", 9, "/", False, "", "", "", "", "", "",
                                    client_class=client.WebTransportClient)
        assert cm.exception.status == ExitCode.UNSUPPORTED
        assert "XPRA_MAX_DATAGRAM_FRAME_SIZE" in str(cm.exception)


@unittest.skipUnless(HAVE_AIOQUIC, "aioquic not available")
class DatagramWriteTest(unittest.TestCase):

    def test_capacity_checked_when_sending(self):
        from xpra.net.quic import connection
        for capacity, use_datagram in ((None, False), (4, False), (5, True)):
            with self.subTest(capacity=capacity):
                http = MagicMock()
                transmit = MagicMock()
                pending = []
                with patch.object(connection, "DATAGRAM_PACKET_TYPES", ("test",)), \
                        patch.object(connection, "get_threaded_loop", return_value=MagicMock(call=pending.append)):
                    conn = connection.XpraQuicConnection(http, 0, transmit, "localhost", 443)
                    self.assertEqual(conn.stream_write(b"hello", "test"), 5)

                http.get_datagram_capacity.assert_not_called()
                self.assertEqual(len(pending), 1)
                http.get_datagram_capacity.return_value = capacity
                pending.pop()()
                http.get_datagram_capacity.assert_called_once_with(0)
                if use_datagram:
                    http.send_datagram.assert_called_once_with(0, b"hello")
                    http.send_data.assert_not_called()
                else:
                    http.send_data.assert_called_once_with(stream_id=0, data=b"hello", end_stream=False)
                    http.send_datagram.assert_not_called()
                transmit.assert_called_once_with()
                self.assertEqual(conn.output_bytecount, 5)
                self.assertEqual(conn.output_writecount, 1)


def main():
    unittest.main()


if __name__ == '__main__':
    main()
