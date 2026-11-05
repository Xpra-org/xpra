#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest
from types import SimpleNamespace
from unittest.mock import patch

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
