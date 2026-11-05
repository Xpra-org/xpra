# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from collections.abc import Iterable
from time import monotonic
from typing import Any

from aioquic.quic.congestion.base import register_congestion_control
from aioquic.quic.congestion.reno import RenoCongestionControl
from aioquic.quic.packet_builder import QuicSentPacket

from xpra.log import Logger

log = Logger("quic")

CONGESTION_CONTROL_ALGORITHM = "xpra-reno"


class XpraRenoCongestionControl(RenoCongestionControl):
    """Observe Reno without changing its congestion control decisions.

    Counters cover in-flight QUIC packets, including retransmissions, rather
    than Xpra packets or application payload bytes. Loss events count batches
    reported by recovery, which may belong to the same congestion episode.
    """

    def __init__(self, *, max_datagram_size: int) -> None:
        super().__init__(max_datagram_size=max_datagram_size)
        self._last_log_time = 0.0
        self._statistics: dict[str, Any] = {
            "algorithm": CONGESTION_CONTROL_ALGORITHM,
            "packets-sent": 0,
            "bytes-sent": 0,
            "packets-acked": 0,
            "bytes-acked": 0,
            "packets-lost": 0,
            "bytes-lost": 0,
            "packets-expired": 0,
            "bytes-expired": 0,
            "loss-events": 0,
            "persistent-congestion-events": 0,
            "rtt-samples": 0,
            "rtt-latest-ms": 0.0,
            "rtt-min-ms": 0.0,
            "rtt-smoothed-ms": 0.0,
        }
        self._update_statistics({})

    def get_info(self) -> dict[str, Any]:
        return self._statistics.copy()

    def _update_statistics(self, updates: dict[str, Any]) -> None:
        # Callbacks run on the asyncio thread. Publish a new, flat snapshot so
        # get_info() can read it from other threads without touching live Reno state.
        stats = self._statistics.copy()
        stats.update(updates)
        stats["congestion-window"] = self.congestion_window
        stats["bytes-in-flight"] = self.bytes_in_flight
        if self.ssthresh is not None:
            stats["slow-start-threshold"] = self.ssthresh
        self._statistics = stats

    def _log_statistics(self, event: str, *, force=False) -> None:
        if not log.is_debug_enabled():
            return
        now = monotonic()
        if force or now - self._last_log_time >= 1:
            self._last_log_time = now
            log("QUIC congestion %s %s: %s", self, event, self._statistics)

    def on_packet_sent(self, *, packet: QuicSentPacket) -> None:
        super().on_packet_sent(packet=packet)
        self._update_statistics({
            "packets-sent": self._statistics["packets-sent"] + 1,
            "bytes-sent": self._statistics["bytes-sent"] + packet.sent_bytes,
        })
        self._log_statistics("sent")

    def on_packet_acked(self, *, now: float, packet: QuicSentPacket) -> None:
        super().on_packet_acked(now=now, packet=packet)
        self._update_statistics({
            "packets-acked": self._statistics["packets-acked"] + 1,
            "bytes-acked": self._statistics["bytes-acked"] + packet.sent_bytes,
        })
        self._log_statistics("acked")

    def on_packets_expired(self, *, packets: Iterable[QuicSentPacket]) -> None:
        packets = tuple(packets)
        super().on_packets_expired(packets=packets)
        self._update_statistics({
            "packets-expired": self._statistics["packets-expired"] + len(packets),
            "bytes-expired": self._statistics["bytes-expired"] + sum(p.sent_bytes for p in packets),
        })
        self._log_statistics("expired")

    def on_packets_lost(self, *, now: float, packets: Iterable[QuicSentPacket]) -> None:
        packets = tuple(packets)
        super().on_packets_lost(now=now, packets=packets)
        self._update_statistics({
            "packets-lost": self._statistics["packets-lost"] + len(packets),
            "bytes-lost": self._statistics["bytes-lost"] + sum(p.sent_bytes for p in packets),
            "loss-events": self._statistics["loss-events"] + int(bool(packets)),
        })
        self._log_statistics("lost", force=True)

    def on_persistent_congestion(self) -> None:
        super().on_persistent_congestion()
        self._update_statistics({
            "persistent-congestion-events": self._statistics["persistent-congestion-events"] + 1,
        })
        self._log_statistics("persistent congestion", force=True)

    def on_rtt_measurement(self, *, now: float, rtt: float) -> None:
        super().on_rtt_measurement(now=now, rtt=rtt)
        # These are the RTT samples passed to the controller, without ACK-delay
        # correction. Keep our own EWMA rather than advancing Reno's HyStart monitor.
        samples = self._statistics["rtt-samples"]
        rtt_ms = rtt * 1000
        self._update_statistics({
            "rtt-samples": samples + 1,
            "rtt-latest-ms": rtt_ms,
            "rtt-min-ms": min(self._statistics["rtt-min-ms"], rtt_ms) if samples else rtt_ms,
            "rtt-smoothed-ms": (7 * self._statistics["rtt-smoothed-ms"] + rtt_ms) / 8 if samples else rtt_ms,
        })
        self._log_statistics("rtt")


def get_congestion_control(quic) -> XpraRenoCongestionControl | None:
    # Keep the dependency on aioquic's private recovery attributes in one place.
    recovery = getattr(quic, "_loss", None)
    control = getattr(recovery, "_cc", None)
    return control if isinstance(control, XpraRenoCongestionControl) else None


register_congestion_control(CONGESTION_CONTROL_ALGORITHM, XpraRenoCongestionControl)
