# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from collections.abc import Iterable
from time import monotonic
from typing import Any, NamedTuple

from aioquic.quic.congestion.base import register_congestion_control
from aioquic.quic.congestion.reno import RenoCongestionControl
from aioquic.quic.connection import END_STATES, QuicConnection
from aioquic.quic.packet_builder import QuicSentPacket

from xpra.log import Logger

log = Logger("quic")

CONGESTION_CONTROL_ALGORITHM = "xpra-reno"
SAMPLE_WINDOW = 1.0
SAMPLE_INTERVAL = 0.1
MIN_SAMPLE_DURATION = 0.25


class CongestionSample(NamedTuple):
    start: float
    end: float
    packets_acked: int = 0
    bytes_acked: int = 0
    packets_lost: int = 0
    bytes_lost: int = 0
    rtt_samples: int = 0
    rtt_total: float = 0.0


def get_pending_stream_info(quic: QuicConnection) -> dict[str, int]:
    """Count queued stream bytes on the asyncio thread, excluding data in flight.

    aioquic merges new data and retransmissions into the same pending ranges.
    Split each range at the highest offset previously emitted into STREAM frames.
    These are current stream-byte counts, not cumulative QUIC packet counters.
    """
    new_bytes = retransmit_bytes = 0
    if quic._state not in END_STATES and not quic._close_pending:
        for stream in quic._streams.values():
            sender = stream.sender
            # Reset senders retain their buffers but will never send them again.
            if sender.is_finished or sender._reset_error_code is not None:
                continue
            boundary = sender.highest_offset
            for r in sender._pending:
                retransmit_bytes += max(0, min(r.stop, boundary) - r.start)
                new_bytes += max(0, r.stop - max(r.start, boundary))
    return {
        "pending-new-bytes": new_bytes,
        "pending-retransmit-bytes": retransmit_bytes,
        "pending-bytes": new_bytes + retransmit_bytes,
    }


def get_recent_info(samples: tuple[CongestionSample, ...], started: float | None,
                    now: float, bytes_in_flight: int) -> dict[str, Any]:
    # Buckets crossing the window boundary are retained, so the window has
    # SAMPLE_INTERVAL precision. Reading never mutates the published samples.
    samples = tuple(s for s in samples if s.end > now - SAMPLE_WINDOW)
    duration = min(SAMPLE_WINDOW, max(0.0, now - started)) if samples and started is not None else 0.0
    acked = sum(s.packets_acked for s in samples)
    lost = sum(s.packets_lost for s in samples)
    acked_bytes = sum(s.bytes_acked for s in samples)
    info: dict[str, Any] = {
        "window-ms": int(SAMPLE_WINDOW * 1000),
        "duration-ms": int(duration * 1000),
        "status": "idle" if not samples and bytes_in_flight == 0 else "insufficient",
        "packets-acked": acked,
        "bytes-acked": acked_bytes,
        "packets-lost": lost,
        "bytes-lost": sum(s.bytes_lost for s in samples),
        "rtt-samples": sum(s.rtt_samples for s in samples),
    }
    if duration >= MIN_SAMPLE_DURATION and acked + lost >= 2:
        info["status"] = "active"
        # This is observed QUIC throughput, including retransmissions, and
        # does not estimate link capacity when the application sends little data.
        info["acked-bitrate"] = int(8 * acked_bytes / duration)
        # Use resolved packets as the denominator: packets still in flight and
        # expired packets have not been reported as either acknowledged or lost.
        info["loss-fraction"] = lost / (acked + lost)
    if duration >= MIN_SAMPLE_DURATION:
        # Compare average RTT in the newer half of the window with the older
        # half. A positive delta means RTT is increasing; units are milliseconds.
        midpoint = now - duration / 2
        older = tuple(s for s in samples if (s.start + s.end) / 2 < midpoint)
        newer = tuple(s for s in samples if (s.start + s.end) / 2 >= midpoint)
        older_count = sum(s.rtt_samples for s in older)
        newer_count = sum(s.rtt_samples for s in newer)
        if older_count and newer_count:
            info["rtt-trend-ms"] = 1000 * (
                sum(s.rtt_total for s in newer) / newer_count - sum(s.rtt_total for s in older) / older_count
            )
    return info


class XpraRenoCongestionControl(RenoCongestionControl):
    """Observe Reno without changing its congestion control decisions.

    Counters cover in-flight QUIC packets, including retransmissions, rather
    than Xpra packets or application payload bytes. Loss events count batches
    reported by recovery, which may belong to the same congestion episode.
    """

    def __init__(self, *, max_datagram_size: int) -> None:
        super().__init__(max_datagram_size=max_datagram_size)
        self._last_log_time = 0.0
        self._last_pending_log_time = 0.0
        self._samples: tuple[CongestionSample, ...] = ()
        self._sample_start: float | None = None
        self._last_loss: float | None = None
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
            "pending-new-bytes": 0,
            "pending-retransmit-bytes": 0,
            "pending-bytes": 0,
            "loss-events": 0,
            "persistent-congestion-events": 0,
            "rtt-samples": 0,
            "rtt-latest-ms": 0.0,
            "rtt-min-ms": 0.0,
            "rtt-smoothed-ms": 0.0,
        }
        self._update_statistics({})

    def get_info(self) -> dict[str, Any]:
        stats, samples, started, last_loss = self._snapshot
        now = monotonic()
        info = stats.copy()
        info["recent"] = get_recent_info(samples, started, now, stats["bytes-in-flight"])
        if last_loss is not None:
            info["last-loss-age-ms"] = max(0, int((now - last_loss) * 1000))
        return info

    def update_pending_streams(self, quic: QuicConnection) -> None:
        # Called after transmit(), including ACK and recovery timer processing.
        # Readers on other threads only see the published snapshot.
        pending = get_pending_stream_info(quic)
        self._update_statistics(pending)
        if log.is_debug_enabled():
            now = monotonic()
            if now - self._last_pending_log_time >= 1:
                self._last_pending_log_time = now
                # Recovery logs before its stream delivery callbacks run. Log
                # the resulting queue separately, after packet construction.
                log("QUIC pending stream data %s: %s", self, pending)

    def _record_sample(self, *, packets_acked=0, bytes_acked=0, packets_lost=0, bytes_lost=0, rtt: float | None = None) -> None:
        # Use one local clock for all sampling and reads: aioquic callback times
        # belong to its event loop and may use a different clock origin.
        now = monotonic()
        samples = tuple(s for s in self._samples if s.end > now - SAMPLE_WINDOW)
        if not samples:
            self._sample_start = now
        if samples and now - samples[-1].start < SAMPLE_INTERVAL:
            previous = samples[-1]
            sample = CongestionSample(
                previous.start, now,
                previous.packets_acked + packets_acked, previous.bytes_acked + bytes_acked,
                previous.packets_lost + packets_lost, previous.bytes_lost + bytes_lost,
                previous.rtt_samples + int(rtt is not None), previous.rtt_total + (rtt or 0.0),
            )
            samples = samples[:-1]
        else:
            sample = CongestionSample(now, now, packets_acked, bytes_acked, packets_lost, bytes_lost,
                                      int(rtt is not None), rtt or 0.0)
        self._samples = samples + (sample,)
        if packets_lost:
            self._last_loss = now

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
        # Publish counters, immutable buckets and timestamps together. Readers
        # can age the window during idle periods without touching asyncio state.
        self._snapshot = stats, self._samples, self._sample_start, self._last_loss

    def _log_statistics(self, event: str, *, force=False) -> None:
        if not log.is_debug_enabled():
            return
        now = monotonic()
        if force or now - self._last_log_time >= 1:
            self._last_log_time = now
            log("QUIC congestion %s %s: %s", self, event, self.get_info())

    def on_packet_sent(self, *, packet: QuicSentPacket) -> None:
        super().on_packet_sent(packet=packet)
        self._record_sample()
        self._update_statistics({
            "packets-sent": self._statistics["packets-sent"] + 1,
            "bytes-sent": self._statistics["bytes-sent"] + packet.sent_bytes,
        })
        self._log_statistics("sent")

    def on_packet_acked(self, *, now: float, packet: QuicSentPacket) -> None:
        super().on_packet_acked(now=now, packet=packet)
        self._record_sample(packets_acked=1, bytes_acked=packet.sent_bytes)
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
        lost_bytes = sum(p.sent_bytes for p in packets)
        if packets:
            self._record_sample(packets_lost=len(packets), bytes_lost=lost_bytes)
        self._update_statistics({
            "packets-lost": self._statistics["packets-lost"] + len(packets),
            "bytes-lost": self._statistics["bytes-lost"] + lost_bytes,
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
        self._record_sample(rtt=rtt)
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
