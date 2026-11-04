#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

"""
Stress tests for the two paths of `XpraQuicConnection.stream_write`:
reliable stream data and unreliable QUIC datagrams (`XPRA_QUIC_DATAGRAM_PACKET_TYPES`).

A real aioquic client and server are connected back to back in memory,
so the stream data is chunked, packed into QUIC packets alongside datagram frames,
acknowledged, lost and retransmitted exactly as it would be on the wire.
The receiving `XpraQuicConnection` must hand out the stream bytes and the datagram records
separately: a datagram that lands between two chunks of a large stream write
must never be spliced into the stream.
"""

import random
import datetime
import unittest
from queue import SimpleQueue, Empty
from unittest.mock import patch

try:
    from aioquic.quic.configuration import QuicConfiguration
    from aioquic.quic.connection import QuicConnection
    from aioquic.h3.connection import H3Connection, H3_ALPN
    from aioquic.h3.events import HeadersReceived, DataReceived, DatagramReceived
    from cryptography import x509
    from cryptography.x509.oid import NameOID
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import ec
    HAVE_AIOQUIC = True
except ImportError:
    HAVE_AIOQUIC = False

DATAGRAM_TYPE = "audio-data"
STREAM_TYPE = "draw"
ADDR = ("127.0.0.1", 10000)


def drain(queue: SimpleQueue) -> list[bytes]:
    items = []
    while True:
        try:
            items.append(queue.get_nowait())
        except Empty:
            return items


def make_certificate():
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (
        x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
        .serial_number(1).not_valid_before(now).not_valid_after(now + datetime.timedelta(days=1))
        .sign(key, hashes.SHA256())
    )
    return cert, key


class SyncLoop:
    """ stands in for the threaded asyncio loop: runs the callbacks immediately """
    def __init__(self):
        self.calls = 0

    def call(self, f) -> None:
        self.calls += 1
        f()


class QuicPair:
    """
    An aioquic client and server talking over an in-memory 'link',
    with an HTTP/3 extended CONNECT session (stream 0) carrying xpra data,
    which is what `ClientWebSocketConnection` / `ServerWebSocketConnection` use.
    """

    def __init__(self, cert, key, loss: float = 0, budget: int = 0, seed: int = 0):
        self.now = 0.0
        self.loss = loss
        # how many client packets each `transmit()` is allowed to put on the wire,
        # so that large stream writes are still in flight when datagrams are queued:
        self.budget = budget
        self.random = random.Random(seed)
        self.dropped = 0
        cconfig = QuicConfiguration(alpn_protocols=H3_ALPN, is_client=True,
                                    max_datagram_frame_size=65536, verify_mode=0)
        sconfig = QuicConfiguration(alpn_protocols=H3_ALPN, is_client=False,
                                    max_datagram_frame_size=65536)
        sconfig.certificate = cert
        sconfig.private_key = key
        self.cquic = QuicConnection(configuration=cconfig)
        self.squic = QuicConnection(configuration=sconfig,
                                    original_destination_connection_id=self.cquic.original_destination_connection_id)
        self.chttp = H3Connection(self.cquic)
        self.shttp = H3Connection(self.squic)
        self.receiver = None
        # the order in which the receiver saw stream chunks ("s") and datagrams ("d"):
        self.event_order: list[str] = []
        self.cquic.connect(ADDR, now=self.now)
        self.drain_link()
        assert self.cquic._handshake_complete and self.squic._handshake_complete
        self.stream_id = self.cquic.get_next_available_stream_id()
        self.chttp.send_headers(self.stream_id, [
            (b":method", b"CONNECT"), (b":protocol", b"websocket"), (b":scheme", b"https"),
            (b":authority", b"localhost"), (b":path", b"/"), (b"sec-websocket-protocol", b"xpra"),
        ])
        self.drain_link()

    def lost(self) -> bool:
        if self.loss and self.random.random() < self.loss:
            self.dropped += 1
            return True
        return False

    def step(self, limit: int = 0) -> int:
        """ move packets in both directions once, returns the number of packets moved """
        self.now += 0.005
        moved = 0
        for quic in (self.cquic, self.squic):
            timer = quic.get_timer()
            if timer is not None and timer <= self.now:
                quic.handle_timer(now=self.now)
        for src, dst, src_limit in ((self.cquic, self.squic, limit), (self.squic, self.cquic, 0)):
            count = 0
            for data, _addr in src.datagrams_to_send(now=self.now):
                moved += 1
                count += 1
                if not self.lost():
                    dst.receive_datagram(data, ADDR, now=self.now)
                if src_limit and count >= src_limit:
                    break
        self.process_events()
        return moved

    def process_events(self) -> None:
        while (event := self.cquic.next_event()) is not None:
            self.chttp.handle_event(event)
        while (event := self.squic.next_event()) is not None:
            for http_event in self.shttp.handle_event(event):
                if isinstance(http_event, HeadersReceived):
                    continue
                if isinstance(http_event, DataReceived):
                    self.event_order.append("s")
                elif isinstance(http_event, DatagramReceived):
                    self.event_order.append("d")
                if self.receiver:
                    self.receiver.http_event_received(http_event)

    def transmit(self) -> None:
        self.step(self.budget)

    def drain_link(self, max_rounds: int = 20000) -> None:
        """ keep moving packets (and firing loss recovery timers) until everything has been delivered """
        for _ in range(max_rounds):
            if self.step():
                continue
            quics = (self.cquic, self.squic)
            in_flight = any(space.ack_eliciting_in_flight for quic in quics for space in quic._loss.spaces)
            if not in_flight:
                # nothing to send and nothing waiting for an ack
                # (don't jump to the next timer, that would be the idle timeout)
                return
            # unacknowledged data: jump to the next timer so that loss detection can retransmit it
            timers = [t for t in (quic.get_timer() for quic in quics) if t is not None]
            if timers:
                self.now = max(self.now, min(timers))
        raise RuntimeError("the link did not settle")


@unittest.skipUnless(HAVE_AIOQUIC, "aioquic not available")
class QuicDatagramTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.cert, cls.key = make_certificate()

    def setUp(self):
        self.loop = SyncLoop()
        patcher = patch("xpra.net.quic.connection.get_threaded_loop", return_value=self.loop)
        patcher.start()
        self.addCleanup(patcher.stop)
        patcher = patch("xpra.net.quic.connection.XpraQuicConnection.datagram_packet_types", (DATAGRAM_TYPE, ))
        patcher.start()
        self.addCleanup(patcher.stop)

    def make_pair(self, **kwargs):
        from xpra.net.quic.connection import XpraQuicConnection
        pair = QuicPair(self.cert, self.key, **kwargs)
        sender = XpraQuicConnection(pair.chttp, pair.stream_id, pair.transmit, "localhost", ADDR[1])
        receiver = XpraQuicConnection(pair.shttp, pair.stream_id, pair.transmit, "localhost", ADDR[1])
        # capture the datagram records instead of dropping them:
        receiver.datagram_records = []
        receiver.datagram_received = receiver.datagram_records.append
        pair.receiver = receiver
        return pair, sender

    @staticmethod
    def make_payload(kind: str, index: int, size: int) -> bytes:
        # every payload is unique and self-describing so that splices are easy to spot:
        prefix = f"<{kind}:{index}:{size}>".encode()
        fill = bytes((index + i) & 0xff for i in range(max(0, size - len(prefix))))
        return (prefix + fill)[:max(size, len(prefix))]

    def received(self, pair) -> tuple[bytes, list[bytes]]:
        stream = b"".join(drain(pair.receiver.read_queue))
        datagrams = pair.receiver.datagram_records
        return stream, datagrams

    def check_stream(self, stream: bytes, sent: list[bytes]) -> None:
        expected = b"".join(sent)
        if stream != expected:
            # find where it went wrong, to make failures readable:
            pos = next((i for i, (a, b) in enumerate(zip(stream, expected)) if a != b), min(len(stream), len(expected)))
            self.fail(f"stream data corrupted at offset {pos} of {len(expected)} (received {len(stream)} bytes):"
                      f" got {stream[pos:pos + 32]!r}, expected {expected[pos:pos + 32]!r}")

    def test_stream_only(self):
        pair, sender = self.make_pair(budget=2)
        sent = [self.make_payload("s", i, size) for i, size in enumerate((1, 100, 1500, 64 * 1024, 7, 300 * 1024))]
        for buf in sent:
            assert sender.stream_write(buf, STREAM_TYPE) == len(buf)
        pair.drain_link()
        stream, datagrams = self.received(pair)
        self.check_stream(stream, sent)
        assert not datagrams

    def test_datagram_only(self):
        pair, sender = self.make_pair()
        sent = [self.make_payload("d", i, 20 + (i * 37) % 1000) for i in range(200)]
        for buf in sent:
            assert sender.stream_write(buf, DATAGRAM_TYPE) == len(buf)
        pair.drain_link()
        stream, datagrams = self.received(pair)
        assert not stream, f"datagrams leaked into the stream: {stream[:64]!r}"
        # lossless link: every record arrives whole and in order
        assert datagrams == sent

    def test_datagram_sent_from_loop(self):
        # aioquic is not thread safe: the datagram must be queued from the loop thread,
        # and it must be transmitted straight away rather than waiting for the next stream write
        pair, sender = self.make_pair()
        calls = self.loop.calls
        sender.stream_write(b"hello", DATAGRAM_TYPE)
        assert self.loop.calls == calls + 1
        assert not pair.cquic._datagrams_pending, "datagram was queued but not transmitted"
        assert pair.receiver.datagram_records == [b"hello"]

    def test_interleaved_bursts(self):
        # large stream writes, each followed by a burst of datagrams while the stream data is still in flight
        pair, sender = self.make_pair(budget=3)
        rng = random.Random(1)
        sent_stream: list[bytes] = []
        sent_datagrams: list[bytes] = []
        for i in range(12):
            buf = self.make_payload("s", i, rng.choice((1024, 50 * 1024, 256 * 1024, 1024 * 1024)))
            sent_stream.append(buf)
            sender.stream_write(buf, STREAM_TYPE)
            for _ in range(rng.randint(1, 40)):
                dgram = self.make_payload("d", len(sent_datagrams), rng.randint(1, 1000))
                sent_datagrams.append(dgram)
                sender.stream_write(dgram, DATAGRAM_TYPE)
        pair.drain_link()
        # make sure this test actually exercises the problem:
        # some datagrams must have arrived in between chunks of the same stream write
        order = "".join(pair.event_order)
        assert "sds" in order, "datagrams were not interleaved with stream chunks"
        stream, datagrams = self.received(pair)
        self.check_stream(stream, sent_stream)
        assert datagrams == sent_datagrams

    def test_interleaved_lossy(self):
        pair, sender = self.make_pair(budget=3, loss=0.05, seed=4)
        rng = random.Random(2)
        sent_stream: list[bytes] = []
        sent_datagrams: list[bytes] = []
        for i in range(8):
            buf = self.make_payload("s", i, rng.choice((4096, 100 * 1024, 512 * 1024)))
            sent_stream.append(buf)
            sender.stream_write(buf, STREAM_TYPE)
            for _ in range(rng.randint(5, 50)):
                dgram = self.make_payload("d", len(sent_datagrams), rng.randint(1, 1000))
                sent_datagrams.append(dgram)
                sender.stream_write(dgram, DATAGRAM_TYPE)
        pair.drain_link()
        assert pair.dropped, "no packets were dropped"
        stream, datagrams = self.received(pair)
        # the stream is retransmitted, so it must still arrive intact:
        self.check_stream(stream, sent_stream)
        # datagrams are not: some are lost, but those that arrive are whole and never duplicated
        assert datagrams, "no datagrams received"
        assert len(datagrams) < len(sent_datagrams), "no datagrams were lost"
        assert len(set(datagrams)) == len(datagrams)
        expected = set(sent_datagrams)
        for dgram in datagrams:
            assert dgram in expected, f"received a corrupted datagram record: {dgram[:64]!r}"

    def test_datagrams_dropped_by_default(self):
        from xpra.net.quic.connection import XpraQuicConnection
        pair, sender = self.make_pair()
        pair.receiver = XpraQuicConnection(pair.shttp, pair.stream_id, pair.transmit, "localhost", ADDR[1])
        for i in range(10):
            sender.stream_write(self.make_payload("d", i, 100), DATAGRAM_TYPE)
        pair.drain_link()
        assert pair.receiver.datagrams_dropped == 10
        assert not drain(pair.receiver.read_queue)

    def test_oversized_datagram(self):
        # a datagram must fit in a single QUIC packet,
        # one that does not must not get stuck and block all the datagrams queued after it
        pair, sender = self.make_pair()
        big = self.make_payload("d", 0, 4000)
        small = self.make_payload("d", 1, 10)
        sender.stream_write(big, DATAGRAM_TYPE)
        sender.stream_write(small, DATAGRAM_TYPE)
        pair.drain_link()
        assert not pair.cquic._datagrams_pending, "datagram stuck in the aioquic send queue"
        stream, datagrams = self.received(pair)
        # the big one is sent reliably on the stream instead:
        assert stream == big
        assert datagrams == [small]


@unittest.skipUnless(HAVE_AIOQUIC, "aioquic not available")
class QuicListenerDatagramTest(unittest.TestCase):

    def test_datagram_routed_to_session(self):
        # `DatagramReceived` has a `stream_id`, not a `flow_id`
        from unittest.mock import MagicMock
        from xpra.net.quic.listener import HttpServerProtocol
        protocol = HttpServerProtocol.__new__(HttpServerProtocol)
        handler = MagicMock()
        protocol._handlers = {0: handler}
        event = DatagramReceived(data=b"foo", stream_id=0)
        protocol.http_event_received(event)
        handler.http_event_received.assert_called_once_with(event)

    def test_client_datagram_routed_to_session(self):
        from unittest.mock import MagicMock
        from xpra.net.quic.client import WebSocketClient
        client = WebSocketClient.__new__(WebSocketClient)
        websocket = MagicMock()
        client._websockets = {0: websocket}
        event = DatagramReceived(data=b"foo", stream_id=0)
        client.http_event_received(event)
        websocket.http_event_received.assert_called_once_with(event)


@unittest.skipUnless(HAVE_AIOQUIC, "aioquic not available")
class QuicDatagramWriteTest(unittest.TestCase):

    def test_write_joins_items(self):
        # a datagram packet type split into multiple items must be written in one go,
        # otherwise the connection could send some items as datagrams and others on the stream
        from unittest.mock import MagicMock
        from xpra.net import packet_encoding, compression
        from xpra.net.protocol.socket_handler import SocketProtocol
        packet_encoding.init_all()
        compression.init_all()
        conn = MagicMock()
        conn.datagram_packet_types = (DATAGRAM_TYPE, )
        conn.write = MagicMock(side_effect=lambda buf, _packet_type: len(buf))
        protocol = SocketProtocol(conn, MagicMock())
        protocol.write_buffers([b"header", b"payload"], DATAGRAM_TYPE, True)
        conn.write.assert_called_once_with(b"headerpayload", DATAGRAM_TYPE)
        conn.write.reset_mock()
        protocol.write_buffers([b"header", b"payload"], STREAM_TYPE, True)
        assert conn.write.call_count == 2


@unittest.skipUnless(HAVE_AIOQUIC, "aioquic not available")
class QuicDatagramProtocolTest(unittest.TestCase):
    """ the protocol layer: one-shot parsing of datagram records """

    @classmethod
    def setUpClass(cls):
        from xpra.net import packet_encoding, compression
        packet_encoding.init_all()
        compression.init_all()
        cls.cert, cls.key = make_certificate()

    def setUp(self):
        self.loop = SyncLoop()
        patcher = patch("xpra.net.quic.connection.get_threaded_loop", return_value=self.loop)
        patcher.start()
        self.addCleanup(patcher.stop)

    def make_protocol(self, conn, received: list | None = None):
        from unittest.mock import MagicMock
        from xpra.net.websockets.protocol import WebSocketProtocol
        callback = (lambda _proto, packet: received.append(packet)) if received is not None else MagicMock()
        protocol = WebSocketProtocol(conn, callback)
        protocol.enable_encoder("rencodeplus")
        protocol.enable_compressor("lz4")
        protocol.datagram_packet_types = (DATAGRAM_TYPE, )
        return protocol

    def encode(self, protocol, packet, level: int = 0) -> list:
        """ returns the items the protocol would write for this packet """
        protocol.set_compression_level(level)
        items = []
        with patch.object(protocol, "raw_write", lambda buf_data, *_args, **_kwargs: items.extend(buf_data)):
            protocol._add_chunks_to_queue(packet[0], protocol.encode(packet))
        return items

    @staticmethod
    def audio_packet(size: int = 992, sequence: int = 0) -> tuple:
        from xpra.net.compression import Compressed
        metadata = {"timestamp": 123456789012345, "duration": 20000000, "sequence": sequence}
        return DATAGRAM_TYPE, "opus+rtp", Compressed("opus+rtp", bytes(i & 0xff for i in range(size))), metadata

    def receiver(self):
        from unittest.mock import MagicMock
        from xpra.net.quic.connection import XpraQuicConnection
        conn = XpraQuicConnection(MagicMock(), 0, MagicMock(), "localhost", ADDR[1])
        received: list = []
        return self.make_protocol(conn, received), received

    def test_parse(self):
        protocol, received = self.receiver()
        for level in (0, 1):
            items = self.encode(protocol, self.audio_packet(), level)
            assert len(items) == 1
            protocol._conn.datagram_received(items[0])
        assert len(received) == 2
        for packet in received:
            assert packet.get_type() == DATAGRAM_TYPE
            assert packet.get_str(1) == "opus+rtp"
            assert bytes(packet.get_buffer(2)) == bytes(i & 0xff for i in range(992))
            assert packet.get_dict(3)["sequence"] == 0
        assert protocol.datagram_stats["received"] == 2

    def test_invalid_records_are_dropped(self):
        protocol, received = self.receiver()
        record = bytes(self.encode(protocol, self.audio_packet())[0])
        invalid = (
            b"",
            record[:1],
            record[:-1],                            # truncated
            record + b"x",                          # trailing data
            record[:2] + b"\0" + record[3:],        # websocket header corrupted
            bytes([0x01]) + record[1:],             # websocket text frame, no fin
        )
        for data in invalid:
            protocol.process_datagram(data)
        assert not received
        assert protocol.datagram_stats["invalid"] == len(invalid)
        assert not protocol.is_closed()

    def test_unwanted_packet_type_dropped(self):
        protocol, received = self.receiver()
        protocol.datagram_packet_types = ()
        protocol.process_datagram(self.encode(protocol, self.audio_packet())[0])
        assert not received
        assert protocol.datagram_stats["dropped"] == 1

    def test_closed(self):
        protocol, received = self.receiver()
        record = self.encode(protocol, self.audio_packet())[0]
        protocol.close()
        protocol.process_datagram(record)
        assert not received

    def negotiate(self, *protocols) -> None:
        """ each protocol parses the network capabilities the other one would send in its hello """
        from xpra.util.objects import typedict
        a, b = protocols
        for protocol, peer in ((a, b), (b, a)):
            protocol.datagram_packet_types = ()
            protocol.parse_remote_caps(typedict(peer.get_datagram_caps()))

    def test_end_to_end(self):
        # sender protocol -> quic connection -> aioquic -> quic connection -> receiver protocol,
        # interleaved with large stream writes
        from xpra.net.quic.connection import XpraQuicConnection
        pair = QuicPair(self.cert, self.key, budget=3)
        with patch("xpra.net.quic.connection.DATAGRAM_PACKET_TYPES", (DATAGRAM_TYPE, )):
            sender_conn = XpraQuicConnection(pair.chttp, pair.stream_id, pair.transmit, "localhost", ADDR[1])
            receiver_conn = XpraQuicConnection(pair.shttp, pair.stream_id, pair.transmit, "localhost", ADDR[1])
            pair.receiver = receiver_conn
            sender = self.make_protocol(sender_conn)
            received: list = []
            receiver = self.make_protocol(receiver_conn, received)
            self.negotiate(sender, receiver)
            assert sender_conn.datagram_packet_types == (DATAGRAM_TYPE, )
            assert receiver.datagram_packet_types == (DATAGRAM_TYPE, )
            stream_bytes = 0
            for i in range(20):
                big = b"%i" % i * (64 * 1024)
                stream_bytes += len(big)
                sender_conn.stream_write(big, STREAM_TYPE)
                for j in range(5):
                    items = self.encode(sender, self.audio_packet(sequence=i * 5 + j))
                    sender.write_buffers(items, DATAGRAM_TYPE, True)
            pair.drain_link()
        assert "sds" in "".join(pair.event_order)
        assert [packet.get_dict(3)["sequence"] for packet in received] == list(range(100))
        assert receiver.datagram_stats == {"received": 100, "invalid": 0, "dropped": 0}
        assert len(b"".join(drain(receiver_conn.read_queue))) == stream_bytes


@unittest.skipUnless(HAVE_AIOQUIC, "aioquic not available")
class QuicDatagramNegotiationTest(unittest.TestCase):

    def setUp(self):
        from xpra.net import packet_encoding, compression
        packet_encoding.init_all()
        compression.init_all()

    def make(self, conn):
        from unittest.mock import MagicMock
        from xpra.net.protocol.socket_handler import SocketProtocol
        return SocketProtocol(conn, MagicMock())

    @staticmethod
    def quic_conn():
        from unittest.mock import MagicMock
        from xpra.net.quic.connection import XpraQuicConnection
        return XpraQuicConnection(MagicMock(), 0, MagicMock(), "localhost", ADDR[1])

    @staticmethod
    def caps(**kwargs):
        from xpra.util.objects import typedict
        return typedict(kwargs)

    def test_advertised(self):
        from xpra.net.common import DATAGRAM_ACCEPT_PACKET_TYPES
        assert "audio-data" in DATAGRAM_ACCEPT_PACKET_TYPES
        protocol = self.make(self.quic_conn())
        assert protocol.get_datagram_caps() == {"datagram-packet-types": DATAGRAM_ACCEPT_PACKET_TYPES}

    def test_not_advertised(self):
        # only advertise on connections that can deliver datagrams to us
        from unittest.mock import MagicMock
        from xpra.net.net_util import get_network_caps
        from xpra.net.quic.client import ClientWebTransportConnection
        from xpra.net.quic.webtransport import ServerWebTransportConnection
        assert "datagram-packet-types" not in get_network_caps()
        conns = (
            ClientWebTransportConnection(MagicMock(), 0, MagicMock(), "localhost", ADDR[1]),
            ServerWebTransportConnection(MagicMock(), {}, 0, MagicMock()),
        )
        for conn in conns:
            with self.subTest(conn=type(conn).__name__):
                assert not conn.datagram
                protocol = self.make(conn)
                assert protocol.get_datagram_caps() == {}
                protocol.parse_remote_caps(self.caps(**{"datagram-packet-types": ("audio-data", )}))
                assert not protocol.datagram_packet_types
                assert not conn.datagram_packet_types

    def test_nothing_before_hello(self):
        conn = self.quic_conn()
        protocol = self.make(conn)
        assert not protocol.datagram_packet_types
        assert not conn.datagram_packet_types

    def test_negotiated(self):
        conn = self.quic_conn()
        protocol = self.make(conn)
        with patch("xpra.net.quic.connection.DATAGRAM_PACKET_TYPES", ("audio-data", "other")), \
                patch("xpra.net.protocol.socket_handler.DATAGRAM_ACCEPT_PACKET_TYPES", ("audio-data", )):
            protocol.parse_remote_caps(self.caps(**{"datagram-packet-types": ("audio-data", "third")}))
        assert protocol.datagram_packet_types == ("audio-data", )
        # we only send what we want to send and the peer accepts:
        assert conn.datagram_packet_types == ("audio-data", )

    def test_peer_does_not_accept_datagrams(self):
        # ie: an older peer
        conn = self.quic_conn()
        protocol = self.make(conn)
        with patch("xpra.net.quic.connection.DATAGRAM_PACKET_TYPES", ("audio-data", )):
            protocol.parse_remote_caps(self.caps())
        assert not conn.datagram_packet_types

    def test_connection_without_datagrams(self):
        from unittest.mock import MagicMock
        conn = MagicMock()
        conn.datagram = False
        protocol = self.make(conn)
        protocol.parse_remote_caps(self.caps(**{"datagram-packet-types": ("audio-data", )}))
        assert not protocol.datagram_packet_types
        conn.set_remote_datagram_packet_types.assert_not_called()


def main():
    unittest.main()


if __name__ == '__main__':
    main()
