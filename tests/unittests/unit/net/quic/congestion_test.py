#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

try:
    import aioquic
    HAVE_AIOQUIC = bool(aioquic)
except ImportError:
    HAVE_AIOQUIC = False


def packet(number: int):
    from aioquic.quic.packet import QuicPacketType
    from aioquic.quic.packet_builder import QuicSentPacket
    from aioquic.tls import Epoch
    return QuicSentPacket(
        epoch=Epoch.ONE_RTT, in_flight=True, is_ack_eliciting=True, is_crypto_packet=False,
        packet_number=number, packet_type=QuicPacketType.ONE_RTT, sent_time=1 + number * 0.001, sent_bytes=1200,
    )


@unittest.skipUnless(HAVE_AIOQUIC, "aioquic not available")
class QuicCongestionTest(unittest.TestCase):

    def make_quic(self):
        from aioquic.quic.configuration import QuicConfiguration
        from aioquic.quic.connection import QuicConnection
        from xpra.net.quic.congestion import CONGESTION_CONTROL_ALGORITHM
        return QuicConnection(configuration=QuicConfiguration(congestion_control_algorithm=CONGESTION_CONTROL_ALGORITHM))

    def test_preserves_reno(self):
        from aioquic.quic.congestion.reno import RenoCongestionControl
        from xpra.net.quic.congestion import XpraRenoCongestionControl
        observed = XpraRenoCongestionControl(max_datagram_size=1200)
        reno = RenoCongestionControl(max_datagram_size=1200)

        def compare(method, **kwargs):
            for control in (observed, reno):
                getattr(control, method)(**kwargs)
            self.assertEqual(observed.get_log_data(), reno.get_log_data())

        packets = [packet(i) for i in range(5)]
        for p in packets:
            compare("on_packet_sent", packet=p)
        compare("on_packet_acked", now=1.1, packet=packets[0])
        # Use separate one-shot iterators: instrumentation must not consume the
        # iterable before Reno has accounted for the packets.
        for control in (observed, reno):
            control.on_packets_lost(now=1.2, packets=iter(packets[1:3]))
            control.on_packets_expired(packets=iter(packets[3:]))
        self.assertEqual(observed.get_log_data(), reno.get_log_data())
        persistent_congestion = hasattr(reno, "on_persistent_congestion")
        if persistent_congestion:
            compare("on_persistent_congestion")
        for i in range(30):
            compare("on_rtt_measurement", now=2 + i * 0.01, rtt=0.05 if i < 10 else 0.1)

        info = observed.get_info()
        self.assertEqual(info["packets-sent"], 5)
        self.assertEqual(info["bytes-sent"], 6000)
        self.assertEqual(info["packets-acked"], 1)
        self.assertEqual(info["bytes-acked"], 1200)
        self.assertEqual(info["packets-lost"], 2)
        self.assertEqual(info["bytes-lost"], 2400)
        self.assertEqual(info["packets-expired"], 2)
        self.assertEqual(info["bytes-expired"], 2400)
        self.assertEqual(info["loss-events"], 1)
        self.assertEqual(info["persistent-congestion-events"], int(persistent_congestion))
        self.assertEqual(info["bytes-in-flight"], 0)
        self.assertEqual(info["rtt-samples"], 30)
        self.assertEqual(info["rtt-min-ms"], 50)
        self.assertEqual(info["rtt-latest-ms"], 100)
        self.assertAlmostEqual(info["rtt-smoothed-ms"], 100 - 50 * (7 / 8) ** 20)

    def test_recovery_callbacks(self):
        from aioquic.quic.rangeset import RangeSet
        from aioquic.quic.recovery import QuicPacketSpace
        from xpra.net.quic.congestion import get_congestion_control
        quic = self.make_quic()
        recovery = quic._loss
        space = QuicPacketSpace()
        recovery.spaces.append(space)
        for i in range(6):
            recovery.on_packet_sent(packet=packet(i), space=space)
        # ACK the last two packets; the packet threshold declares the first
        # three lost, leaving one in flight until the space is discarded.
        recovery.on_ack_received(ack_rangeset=RangeSet([range(4, 6)]), ack_delay=0, now=1.1, space=space)
        control = get_congestion_control(quic)
        info = control.get_info()
        self.assertEqual(info["packets-acked"], 2)
        self.assertEqual(info["packets-lost"], 3)
        self.assertEqual(info["loss-events"], 1)
        self.assertEqual(info["bytes-in-flight"], 1200)
        self.assertEqual(info["congestion-window"], 7200)
        self.assertAlmostEqual(info["rtt-latest-ms"], 95)
        recovery.discard_space(space)
        info = control.get_info()
        self.assertEqual(info["packets-expired"], 1)
        self.assertEqual(info["packets-lost"], 3)
        self.assertEqual(info["bytes-in-flight"], 0)

    def test_connection_snapshots(self):
        from xpra.net.quic.connection import XpraQuicConnection
        quic = self.make_quic()
        http = SimpleNamespace(_quic=quic)
        first = XpraQuicConnection(http, 0, lambda: None, "localhost", 443)
        shared = XpraQuicConnection(http, 4, lambda: None, "localhost", 443)
        other = XpraQuicConnection(SimpleNamespace(_quic=self.make_quic()), 0, lambda: None, "localhost", 443)
        self.assertIs(first.congestion_control, shared.congestion_control)
        self.assertIsNot(first.congestion_control, other.congestion_control)
        before = first.get_info()["quic"]["congestion"]
        first.congestion_control.on_packet_sent(packet=packet(0))
        self.assertEqual(before["bytes-in-flight"], 0)
        self.assertEqual(before["recent"]["status"], "idle")
        info = shared.get_info()["quic"]["congestion"]
        self.assertEqual(info["bytes-in-flight"], 1200)
        self.assertEqual(other.get_info()["quic"]["congestion"]["bytes-in-flight"], 0)
        info["bytes-in-flight"] = -1
        info["recent"]["status"] = "changed"
        self.assertEqual(first.get_info()["quic"]["congestion"]["bytes-in-flight"], 1200)
        self.assertEqual(first.get_info()["quic"]["congestion"]["recent"]["status"], "insufficient")

    def test_pending_stream_ranges(self):
        from aioquic.quic.packet_builder import QuicDeliveryState
        from aioquic.quic.stream import QuicStream
        from xpra.net.quic.congestion import get_pending_stream_info
        quic = self.make_quic()
        stream = QuicStream(stream_id=0)
        quic._streams[0] = stream
        sender = stream.sender

        def check(new_bytes, retransmit_bytes):
            self.assertEqual(get_pending_stream_info(quic), {
                "pending-new-bytes": new_bytes,
                "pending-retransmit-bytes": retransmit_bytes,
                "pending-bytes": new_bytes + retransmit_bytes,
            })

        check(0, 0)
        sender.write(bytes(1000))
        check(1000, 0)
        sender.get_frame(400)
        check(600, 0)  # Bytes already in flight are excluded.
        sender.on_data_delivery(QuicDeliveryState.LOST, 0, 400, False)
        check(600, 400)  # aioquic merges these into one range crossing highest_offset.
        sender.get_frame(250)
        check(600, 150)
        sender.get_frame(300)  # Retransmission and first transmission in the same frame.
        check(450, 0)
        sender.on_data_delivery(QuicDeliveryState.LOST, 250, 550, False)
        sender.on_data_delivery(QuicDeliveryState.LOST, 250, 550, False)
        check(450, 300)  # Repeated loss notifications do not count a byte twice.
        sender.get_frame(750)
        check(0, 0)
        sender.on_data_delivery(QuicDeliveryState.ACKED, 0, 1000, False)
        check(0, 0)

    def test_pending_stream_scope(self):
        from aioquic.quic.connection import QuicConnectionState
        from aioquic.quic.packet_builder import QuicDeliveryState
        from aioquic.quic.stream import QuicStream
        from xpra.net.quic.congestion import get_pending_stream_info
        quic = self.make_quic()
        for stream_id, size in ((0, 1000), (4, 500), (8, 200)):
            stream = QuicStream(stream_id=stream_id)
            stream.sender.write(bytes(size))
            quic._streams[stream_id] = stream
        sender = quic._streams[4].sender
        sender.get_frame(100)
        sender.on_data_delivery(QuicDeliveryState.LOST, 0, 100, False)
        quic._streams[8].sender.reset(0)  # Reset senders retain their pending ranges.
        quic.send_datagram_frame(bytes(300))  # Unreliable datagrams are not stream backlog.
        expected = {"pending-new-bytes": 1400, "pending-retransmit-bytes": 100, "pending-bytes": 1500}
        self.assertEqual(get_pending_stream_info(quic), expected)
        quic.close()
        self.assertEqual(get_pending_stream_info(quic)["pending-bytes"], 0)
        quic._close_pending = False
        for state in (QuicConnectionState.CLOSING, QuicConnectionState.DRAINING, QuicConnectionState.TERMINATED):
            with self.subTest(state=state):
                quic._state = state
                self.assertEqual(get_pending_stream_info(quic)["pending-bytes"], 0)

    def test_pending_connection_snapshots(self):
        from aioquic.quic.stream import QuicStream
        from xpra.net.quic.connection import XpraQuicConnection
        quic = self.make_quic()
        http = SimpleNamespace(_quic=quic)
        first = XpraQuicConnection(http, 0, lambda: None, "localhost", 443)
        shared = XpraQuicConnection(http, 4, lambda: None, "localhost", 443)
        other = XpraQuicConnection(SimpleNamespace(_quic=self.make_quic()), 0, lambda: None, "localhost", 443)
        before = first.get_info()["quic"]["congestion"]
        stream = QuicStream(stream_id=0)
        quic._streams[0] = stream
        stream.sender.write(bytes(1000))
        first.congestion_control.update_pending_streams(quic)
        stream.sender.get_frame(400)
        # get_info() must not inspect live asyncio state, even after it changes.
        self.assertEqual(shared.get_info()["quic"]["congestion"]["pending-new-bytes"], 1000)
        self.assertEqual(before["pending-bytes"], 0)
        info = shared.get_info()["quic"]["congestion"]
        info["pending-bytes"] = -1
        self.assertEqual(first.get_info()["quic"]["congestion"]["pending-bytes"], 1000)
        self.assertEqual(other.get_info()["quic"]["congestion"]["pending-bytes"], 0)
        first.congestion_control.update_pending_streams(quic)
        self.assertEqual(shared.get_info()["quic"]["congestion"]["pending-bytes"], 600)

    def test_protocol_pending_updates(self):
        from aioquic.quic.packet_builder import QuicDeliveryState
        from xpra.net.quic.client import WebSocketClient, WebTransportClient
        from xpra.net.quic.congestion import get_congestion_control
        from xpra.net.quic.listener import HttpServerProtocol

        async def check_protocols():
            for protocol_class in (WebSocketClient, WebTransportClient, HttpServerProtocol):
                with self.subTest(protocol=protocol_class.__name__):
                    quic = self.make_quic()
                    quic.configuration.alpn_protocols = ["h3"]
                    quic.connect(("127.0.0.1", 443), now=asyncio.get_running_loop().time())
                    protocol = protocol_class(quic)
                    protocol.connection_made(MagicMock())
                    control = get_congestion_control(quic)
                    try:
                        protocol.transmit()
                        baseline = control.get_info()["pending-new-bytes"]
                        stream_id = quic.get_next_available_stream_id()
                        quic.send_stream_data(stream_id, bytes(1000))
                        protocol.transmit()
                        self.assertEqual(control.get_info()["pending-new-bytes"], baseline + 1000)
                        # No handshake response yet: stream bytes stay queued.
                        sender = quic._streams[stream_id].sender
                        sender.get_frame(400)
                        sender.on_data_delivery(QuicDeliveryState.LOST, 0, 400, False)
                        protocol.transmit()  # No new application write is needed.
                        info = control.get_info()
                        self.assertEqual(info["pending-new-bytes"], baseline + 600)
                        self.assertEqual(info["pending-retransmit-bytes"], 400)
                        quic.close()
                        protocol.transmit()
                        self.assertEqual(control.get_info()["pending-bytes"], 0)
                    finally:
                        if protocol._timer:
                            protocol._timer.cancel()

        asyncio.run(check_protocols())

    def test_pending_debug_logging(self):
        from aioquic.quic.stream import QuicStream
        from xpra.net.quic.congestion import get_congestion_control
        quic = self.make_quic()
        control = get_congestion_control(quic)
        stream = QuicStream(stream_id=0)
        quic._streams[0] = stream
        stream.sender.write(bytes(1000))
        with patch("xpra.net.quic.congestion.log") as log, patch("xpra.net.quic.congestion.monotonic", return_value=10) as clock:
            log.is_debug_enabled.return_value = False
            control.update_pending_streams(quic)
            log.assert_not_called()
            log.is_debug_enabled.return_value = True
            control.update_pending_streams(quic)
            self.assertEqual(log.call_count, 1)
            self.assertEqual(log.call_args.args[-1], {
                "pending-new-bytes": 1000, "pending-retransmit-bytes": 0, "pending-bytes": 1000,
            })
            stream.sender.get_frame(1000)
            clock.return_value = 10.5
            control.update_pending_streams(quic)
            self.assertEqual(log.call_count, 1)
            clock.return_value = 11
            control.update_pending_streams(quic)
            self.assertEqual(log.call_count, 2)
            self.assertEqual(log.call_args.args[-1]["pending-bytes"], 0)

    def test_recent_rates_and_idle(self):
        from xpra.net.quic.congestion import XpraRenoCongestionControl
        with patch("xpra.net.quic.congestion.monotonic", return_value=0) as clock:
            control = XpraRenoCongestionControl(max_datagram_size=1200)
            info = control.get_info()
            self.assertEqual(info["recent"]["status"], "idle")
            self.assertNotIn("last-loss-age-ms", info)
            packets = [packet(i) for i in range(4)]
            for p in packets:
                control.on_packet_sent(packet=p)
            clock.return_value = 0.125
            control.on_packet_acked(now=1.1, packet=packets[0])
            recent = control.get_info()["recent"]
            self.assertEqual(recent["status"], "insufficient")
            self.assertNotIn("acked-bitrate", recent)
            self.assertNotIn("loss-fraction", recent)

            clock.return_value = 0.5
            control.on_packet_acked(now=1.2, packet=packets[1])
            control.on_packets_lost(now=1.2, packets=iter([packets[2]]))
            control.on_packets_expired(packets=iter([packets[3]]))
            info = control.get_info()
            recent = info["recent"]
            self.assertEqual(recent["status"], "active")
            self.assertEqual(recent["duration-ms"], 500)
            self.assertEqual(recent["acked-bitrate"], 38400)
            self.assertEqual(recent["packets-acked"], 2)
            self.assertEqual(recent["bytes-lost"], 1200)
            self.assertEqual(recent["loss-fraction"], 1 / 3)
            self.assertEqual(info["last-loss-age-ms"], 0)

            # Reads must age both the rate and the last loss without callbacks.
            clock.return_value = 0.75
            info = control.get_info()
            self.assertEqual(info["recent"]["acked-bitrate"], 25600)
            self.assertEqual(info["last-loss-age-ms"], 250)
            clock.return_value = 1.5
            info = control.get_info()
            self.assertEqual(info["recent"]["status"], "idle")
            self.assertEqual(info["recent"]["bytes-acked"], 0)
            self.assertEqual(info["recent"]["bytes-lost"], 0)
            self.assertNotIn("acked-bitrate", info["recent"])
            self.assertNotIn("loss-fraction", info["recent"])
            self.assertEqual(info["last-loss-age-ms"], 1000)
            self.assertEqual(info["packets-lost"], 1)

    def test_recent_sampling_restarts_after_idle(self):
        from xpra.net.quic.congestion import XpraRenoCongestionControl
        with patch("xpra.net.quic.congestion.monotonic", return_value=0) as clock:
            control = XpraRenoCongestionControl(max_datagram_size=1200)
            control.on_packet_sent(packet=packet(0))
            clock.return_value = 0.25
            control.on_packet_acked(now=1.1, packet=packet(0))
            self.assertEqual(control.get_info()["recent"]["status"], "insufficient")
            clock.return_value = 10
            for i in (1, 2):
                control.on_packet_sent(packet=packet(i))
            clock.return_value = 10.125
            for i in (1, 2):
                control.on_packet_acked(now=2.1, packet=packet(i))
            recent = control.get_info()["recent"]
            self.assertEqual(recent["status"], "insufficient")
            self.assertNotIn("acked-bitrate", recent)
            clock.return_value = 10.25
            recent = control.get_info()["recent"]
            self.assertEqual(recent["status"], "active")
            self.assertEqual(recent["duration-ms"], 250)
            self.assertEqual(recent["bytes-acked"], 2400)
            self.assertEqual(recent["acked-bitrate"], 76800)
            self.assertEqual(control.get_info()["bytes-acked"], 3600)

    def test_outstanding_packets_are_not_idle(self):
        from xpra.net.quic.congestion import XpraRenoCongestionControl
        with patch("xpra.net.quic.congestion.monotonic", return_value=0) as clock:
            control = XpraRenoCongestionControl(max_datagram_size=1200)
            control.on_packet_sent(packet=packet(0))
            clock.return_value = 10
            recent = control.get_info()["recent"]
            self.assertEqual(recent["status"], "insufficient")
            self.assertNotIn("acked-bitrate", recent)

    def test_recent_window_rollover(self):
        from xpra.net.quic.congestion import XpraRenoCongestionControl
        with patch("xpra.net.quic.congestion.monotonic", return_value=0) as clock:
            control = XpraRenoCongestionControl(max_datagram_size=1200)
            for i in range(4):
                control.on_packet_sent(packet=packet(i))
            clock.return_value = 0.25
            control.on_packets_lost(now=1.1, packets=iter([packet(0)]))
            control.on_packet_acked(now=1.1, packet=packet(1))
            clock.return_value = 1
            control.on_packet_acked(now=2, packet=packet(2))
            clock.return_value = 1.5
            control.on_packet_acked(now=2.5, packet=packet(3))
            info = control.get_info()
            recent = info["recent"]
            self.assertEqual(recent["window-ms"], 1000)
            self.assertEqual(recent["duration-ms"], 1000)
            self.assertEqual(recent["bytes-acked"], 2400)
            self.assertEqual(recent["acked-bitrate"], 19200)
            self.assertEqual(recent["loss-fraction"], 0)
            self.assertEqual(recent["bytes-lost"], 0)
            self.assertEqual(info["bytes-lost"], 1200)

    def test_recent_rtt_trend(self):
        from xpra.net.quic.congestion import XpraRenoCongestionControl
        for old_rtt, new_rtt, delta_ms in ((0.05, 0.09, 40), (0.09, 0.05, -40), (0.05, 0.05, 0)):
            with self.subTest(delta_ms=delta_ms), patch("xpra.net.quic.congestion.monotonic", return_value=0) as clock:
                control = XpraRenoCongestionControl(max_datagram_size=1200)
                for i in range(4):
                    control.on_packet_sent(packet=packet(i))
                for i, t in enumerate((0.2, 0.4, 0.6, 0.8)):
                    clock.return_value = t
                    control.on_packet_acked(now=2 + t, packet=packet(i))
                    control.on_rtt_measurement(now=2 + t, rtt=old_rtt if t < 0.5 else new_rtt)
                clock.return_value = 1
                recent = control.get_info()["recent"]
                self.assertEqual(recent["rtt-samples"], 4)
                self.assertAlmostEqual(recent["rtt-trend-ms"], delta_ms)
                clock.return_value = 1.5
                self.assertNotIn("rtt-trend-ms", control.get_info()["recent"])

    def test_sampling_buckets_are_bounded(self):
        from xpra.net.quic.congestion import XpraRenoCongestionControl
        with patch("xpra.net.quic.congestion.monotonic", return_value=0) as clock:
            control = XpraRenoCongestionControl(max_datagram_size=1200)
            for i in range(3000):
                clock.return_value = i / 1000
                p = packet(i)
                control.on_packet_sent(packet=p)
                control.on_packet_acked(now=5 + i / 1000, packet=p)
            self.assertLessEqual(len(control._samples), 11)
            info = control.get_info()
            self.assertEqual(info["packets-acked"], 3000)
            self.assertEqual(info["recent"]["status"], "active")
            self.assertLessEqual(info["recent"]["packets-acked"], 1100)

    def test_client_configuration(self):
        from aioquic.quic.connection import QuicConnection
        from xpra.net.quic.client import _make_quic_configuration
        from xpra.net.quic.congestion import XpraRenoCongestionControl, get_congestion_control
        config = _make_quic_configuration("", "", "", "", "none", "", "localhost")
        self.assertIsInstance(get_congestion_control(QuicConnection(configuration=config)), XpraRenoCongestionControl)

    def test_debug_logging(self):
        from xpra.net.quic.congestion import XpraRenoCongestionControl
        control = XpraRenoCongestionControl(max_datagram_size=1200)
        with patch("xpra.net.quic.congestion.log") as log, patch("xpra.net.quic.congestion.monotonic", return_value=10) as clock:
            log.is_debug_enabled.return_value = False
            control.on_packet_sent(packet=packet(0))
            log.assert_not_called()
            log.is_debug_enabled.return_value = True
            control.on_packet_sent(packet=packet(1))
            control.on_packet_sent(packet=packet(2))
            self.assertEqual(log.call_count, 1)
            control.on_packets_lost(now=1.2, packets=iter([packet(0)]))
            self.assertEqual(log.call_count, 2)
            self.assertEqual(log.call_args.args[-1]["packets-lost"], 1)
            self.assertEqual(log.call_args.args[-1]["congestion-window"], 6000)
            self.assertEqual(log.call_args.args[-1]["recent"]["status"], "insufficient")
            clock.return_value = 10.5
            control.on_packet_acked(now=1.3, packet=packet(1))
            clock.return_value = 11
            control.on_packet_acked(now=1.4, packet=packet(2))
            self.assertEqual(log.call_count, 3)
            self.assertEqual(log.call_args.args[-1]["recent"]["acked-bitrate"], 19200)
            self.assertEqual(log.call_args.args[-1]["last-loss-age-ms"], 1000)


if __name__ == "__main__":
    unittest.main()
