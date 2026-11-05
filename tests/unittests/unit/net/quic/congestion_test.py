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
        info = shared.get_info()["quic"]["congestion"]
        self.assertEqual(info["bytes-in-flight"], 1200)
        self.assertEqual(other.get_info()["quic"]["congestion"]["bytes-in-flight"], 0)
        info["bytes-in-flight"] = -1
        self.assertEqual(first.get_info()["quic"]["congestion"]["bytes-in-flight"], 1200)

    def test_client_configuration(self):
        from aioquic.quic.connection import QuicConnection
        from xpra.net.quic.client import _make_quic_configuration
        from xpra.net.quic.congestion import XpraRenoCongestionControl, get_congestion_control
        config = _make_quic_configuration("", "", "", "", "none", "", "localhost")
        self.assertIsInstance(get_congestion_control(QuicConnection(configuration=config)), XpraRenoCongestionControl)

    def test_debug_logging(self):
        from xpra.net.quic.congestion import XpraRenoCongestionControl
        control = XpraRenoCongestionControl(max_datagram_size=1200)
        with patch("xpra.net.quic.congestion.log") as log, patch("xpra.net.quic.congestion.monotonic", return_value=10):
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


if __name__ == "__main__":
    unittest.main()
