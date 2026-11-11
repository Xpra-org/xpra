#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

"""Deterministic transport validation for #4202; no sockets or network privileges.

PYTHONPATH=. python3 tests/xpra/net/quic_congestion.py --output /tmp/xpra-quic-4202

Real aioquic TLS, recovery and HTTP/3 carry Xpra-framed JPEG draw packets,
damage-sequence acknowledgements and synthetic Opus-sized audio datagrams.
The full desktop, encoder selection and audio playback pipelines are excluded.
"""

import argparse
import csv
import datetime
import heapq
import io
import json
import platform
import random
import statistics
import subprocess
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
from unittest.mock import patch

import aioquic
import numpy as np
from PIL import Image
from aioquic.h3.connection import H3Connection, H3_ALPN
from aioquic.h3.events import HeadersReceived
from aioquic.quic.configuration import QuicConfiguration
from aioquic.quic.connection import QuicConnection
from cryptography import x509
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

from xpra.net.protocol.header import FLAGS_RENCODEPLUS, HEADER_SIZE, pack_header, unpack_header
from xpra.net.quic.connection import XpraQuicConnection
from xpra.net.quic.congestion import CONGESTION_CONTROL_ALGORITHM
from xpra.net.rencodeplus.rencodeplus import dumps, loads

ADDR = ("127.0.0.1", 4202)
TICK = 0.001
SAMPLE_PERIOD = 0.1


@dataclass(frozen=True)
class Phase:
    name: str
    seconds: float
    mbps: float = 20
    delay_ms: float = 10
    loss: float = 0
    burst: bool = False


SCENARIOS = {
    "baseline": [Phase("clean", 18)],
    "bandwidth-step": [Phase("20Mbps", 10), Phase("5Mbps", 12, mbps=5), Phase("20Mbps-recovery", 18)],
    "latency-step": [Phase("20ms-RTT", 10), Phase("150ms-RTT", 12, delay_ms=75), Phase("20ms-recovery", 14)],
    "random-loss": [Phase("clean", 8), Phase("0.5%-loss", 16, loss=0.005), Phase("clean-recovery", 14)],
    "burst-loss": [Phase("clean", 8), Phase("100ms-bursts", 12, burst=True), Phase("clean-recovery", 14)],
    "sparse": [Phase("sparse", 12), Phase("idle", 4)],
    "audio": [Phase("clean", 8), Phase("0.5%-loss", 16, loss=0.005), Phase("clean-recovery", 14)],
}


def percentile(values, fraction):
    if not values:
        return None
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int((len(ordered) - 1) * fraction))]


def encode(packet):
    payload = dumps(packet)
    return pack_header(FLAGS_RENCODEPLUS, 0, 0, len(payload)) + payload


def decode(data):
    header = unpack_header(data)
    assert header[:4] == (b"P", FLAGS_RENCODEPLUS, 0, 0), header
    return loads(data[HEADER_SIZE:HEADER_SIZE + header[4]])


def certificate():
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (
        x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
        .serial_number(4202).not_valid_before(now - datetime.timedelta(minutes=1))
        .not_valid_after(now + datetime.timedelta(days=1)).sign(key, hashes.SHA256())
    )
    return cert, key


def jpeg_frames():
    rng = np.random.default_rng(4202)
    frames = []
    for _ in range(8):
        pixels = rng.integers(0, 256, (180, 320, 3), dtype=np.uint8)
        output = io.BytesIO()
        Image.fromarray(pixels).save(output, format="JPEG", quality=75)
        frames.append(output.getvalue())
    return frames


class ImmediateLoop:
    @staticmethod
    def call(callback):
        callback()


class Direction:
    def __init__(self, seed):
        self.random = random.Random(seed)
        self.queue = deque()
        self.queued_bytes = 0
        self.free_at = 0.0
        self.sent = self.random_drops = self.queue_drops = self.burst_drops = 0

    def enqueue(self, now, data, phase, elapsed):
        while self.queue and self.queue[0][0] <= now:
            _, size = self.queue.popleft()
            self.queued_bytes -= size
        self.sent += 1
        # A fixed 100KB drop-tail queue, including the packet in service.
        if self.queued_bytes + len(data) > 100_000:
            self.queue_drops += 1
            return None
        finish = max(now, self.free_at) + len(data) * 8 / (phase.mbps * 1_000_000)
        self.free_at = finish
        self.queue.append((finish, len(data)))
        self.queued_bytes += len(data)
        # Loss consumes serialization capacity, as a corrupted packet would.
        if phase.burst and elapsed % 2 < 0.1:
            self.burst_drops += 1
            return None
        if self.random.random() < phase.loss:
            self.random_drops += 1
            return None
        return finish + phase.delay_ms / 1000


class Experiment:
    def __init__(self, name, seed, cert, key, frames):
        self.name, self.seed, self.frames = name, seed, frames
        self.phases = SCENARIOS[name]
        self.duration = sum(p.seconds for p in self.phases)
        self.now = self.origin = 0.0
        self.events = []
        self.event_id = 0
        self.links = [Direction(seed), Direction(seed + 1000)]
        config = dict(alpn_protocols=H3_ALPN, congestion_control_algorithm=CONGESTION_CONTROL_ALGORITHM,
                      max_datagram_frame_size=65536, max_data=64 * 1024 * 1024, max_stream_data=64 * 1024 * 1024)
        self.client = QuicConnection(configuration=QuicConfiguration(is_client=True, verify_mode=0, **config))
        server_config = QuicConfiguration(is_client=False, **config)
        server_config.certificate, server_config.private_key = cert, key
        self.server = QuicConnection(configuration=server_config,
                                     original_destination_connection_id=self.client.original_destination_connection_id)
        self.quics = [self.client, self.server]
        self.http = [H3Connection(q) for q in self.quics]
        self.connections = [XpraQuicConnection(h, 0, lambda: None, "localhost", 4202) for h in self.http]
        self.connections[1].set_remote_datagram_packet_types(("audio-data",))
        self.connections[0].datagram_received = self.audio_received
        self.buffers = [bytearray(), bytearray()]
        self.frame_records = []
        self.audio_records = []
        self.traces = []
        self.acked_events, self.lost_events = deque(), deque()
        self.reference_start = self.reference_last_activity = None
        self.decode_costs = []
        self.connected = False
        self.install_ledger()

    def install_ledger(self):
        # Independent per-callback ledger to check the bucketed reporting
        # against exact event timestamps, without changing the observer itself.
        control = self.connections[1].congestion_control
        ack, lost = control.on_packet_acked, control.on_packets_lost
        sent, rtt = control.on_packet_sent, control.on_rtt_measurement

        def activity():
            if self.reference_last_activity is None or self.now - self.reference_last_activity >= 1:
                self.reference_start = self.now
            self.reference_last_activity = self.now

        def on_sent(*, packet):
            activity()
            sent(packet=packet)

        def on_ack(*, now, packet):
            activity()
            self.acked_events.append((self.now, packet.sent_bytes))
            ack(now=now, packet=packet)

        def on_lost(*, now, packets):
            packets = tuple(packets)
            if packets:
                activity()
            self.lost_events.extend((self.now, p.sent_bytes) for p in packets)
            lost(now=now, packets=packets)

        def on_rtt(*, now, rtt):
            activity()
            control_rtt(now=now, rtt=rtt)

        control.on_packet_acked, control.on_packets_lost = on_ack, on_lost
        control_rtt = rtt
        control.on_packet_sent, control.on_rtt_measurement = on_sent, on_rtt

    def phase_at(self, elapsed):
        start = 0.0
        for phase in self.phases:
            if elapsed < start + phase.seconds:
                return phase, start
            start += phase.seconds
        return Phase("drain", 120), self.duration

    def schedule(self, when, kind, side, data):
        self.event_id += 1
        heapq.heappush(self.events, (when, self.event_id, kind, side, data))

    def audio_received(self, data):
        packet = decode(data)
        assert packet[0] == "audio-data"
        self.audio_records[packet[3]["sequence"]]["received"] = self.now - self.origin

    def process_http(self, side):
        while (event := self.quics[side].next_event()) is not None:
            for http_event in self.http[side].handle_event(event):
                if isinstance(http_event, HeadersReceived):
                    if side == 1:
                        self.http[1].send_headers(0, [(b":status", b"200")], end_stream=False)
                    else:
                        self.connected = True
                elif getattr(http_event, "stream_id", None) == 0:
                    self.connections[side].http_event_received(http_event)
        connection = self.connections[side]
        while not connection.read_queue.empty():
            self.buffers[side].extend(connection.read(1 << 20))
        buffer = self.buffers[side]
        while len(buffer) >= HEADER_SIZE:
            size = HEADER_SIZE + unpack_header(buffer)[4]
            if len(buffer) < size:
                break
            packet = decode(bytes(buffer[:size]))
            del buffer[:size]
            if side == 0:
                assert packet[0] == "draw"
                sequence = packet[8]
                assert packet[7] == self.frames[sequence % len(self.frames)]
                before = perf_counter()
                Image.open(io.BytesIO(packet[7])).load()
                self.decode_costs.append((perf_counter() - before) * 1000)
                self.frame_records[sequence]["received"] = self.now - self.origin
                # A fixed 1ms client processing delay, independent of host CPU.
                self.schedule(self.now + 0.001, "ack", 0, sequence)
            else:
                assert packet[0] == "damage-sequence"
                self.frame_records[packet[1]]["acked"] = self.now - self.origin

    def tick(self, impairment=True):
        self.now = round(self.now + TICK, 6)
        while self.events and self.events[0][0] <= self.now:
            _, _, kind, side, data = heapq.heappop(self.events)
            if kind == "ack":
                self.connections[0].write(encode(("damage-sequence", data, 1, 320, 180, 1000, "", {})), "damage-sequence")
            else:
                self.quics[side].receive_datagram(data, ADDR, now=self.now)
                self.process_http(side)
        for side, quic in enumerate(self.quics):
            timer = quic.get_timer()
            if timer is not None and timer <= self.now:
                quic.handle_timer(now=self.now)
                self.process_http(side)
        phase, start = self.phase_at(self.now - self.origin) if impairment else (Phase("handshake", 10), 0)
        for side, quic in enumerate(self.quics):
            if not quic._network_paths:
                continue
            for data, _ in quic.datagrams_to_send(now=self.now):
                arrival = self.links[side].enqueue(self.now, data, phase, self.now - self.origin - start)
                if arrival is not None:
                    self.schedule(arrival, "wire", 1 - side, data)

    def send_frame(self):
        sequence = len(self.frame_records)
        jpeg = self.frames[sequence % len(self.frames)]
        packet = ("draw", 1, 0, 0, 320, 180, "jpeg", jpeg, sequence, 320 * 3, {"quality": 75})
        self.frame_records.append({"sequence": sequence, "sent": self.now - self.origin, "bytes": len(jpeg)})
        self.connections[1].write(encode(packet), "draw")

    def send_audio(self):
        sequence = len(self.audio_records)
        self.audio_records.append({"sent": self.now - self.origin})
        packet = ("audio-data", "opus+rtp", bytes(160), {"sequence": sequence})
        self.connections[1].write(encode(packet), "audio-data")

    def sample(self):
        elapsed = self.now - self.origin
        info = self.connections[1].get_info()["quic"]["congestion"]
        recent = info["recent"]
        pending = sum(r.stop - r.start for stream in self.server._streams.values() for r in stream.sender._pending)
        unacked = [f for f in self.frame_records if "acked" not in f]
        for ledger in (self.acked_events, self.lost_events):
            while ledger and ledger[0][0] <= self.now - 1:
                ledger.popleft()
        duration = min(1.0, self.now - self.reference_start) if self.reference_start is not None else 0
        exact_rate = 8 * sum(size for _, size in self.acked_events) / duration if duration else 0
        resolved = len(self.acked_events) + len(self.lost_events)
        exact_fraction = len(self.lost_events) / resolved if resolved else None
        total_resolved = info["bytes-acked"] + info["bytes-lost"] + info["bytes-expired"] + info["bytes-in-flight"]
        assert total_resolved == info["bytes-sent"], info
        row = {
            "time": elapsed, "phase": self.phase_at(elapsed)[0].name, "status": recent["status"],
            "sample-duration-ms": recent["duration-ms"],
            "acked-bps": recent.get("acked-bitrate"), "exact-acked-bps": exact_rate,
            "loss-fraction": recent.get("loss-fraction"), "exact-loss-fraction": exact_fraction,
            "rtt-ms": info["rtt-smoothed-ms"], "rtt-trend-ms": recent.get("rtt-trend-ms"),
            "cwnd": info["congestion-window"], "in-flight": info["bytes-in-flight"], "pending-bytes": pending,
            "cwnd-rate-mbps": 8 * info["congestion-window"] / max(info["rtt-smoothed-ms"], 0.001) / 1000,
            "oldest-unacked-ms": (elapsed - unacked[0]["sent"]) * 1000 if unacked else 0,
            "last-loss-age-ms": info.get("last-loss-age-ms"), "lost-packets": info["packets-lost"],
            "queue-drops": self.links[1].queue_drops, "random-drops": self.links[1].random_drops,
            "burst-drops": self.links[1].burst_drops,
        }
        self.traces.append(row)

    def run(self):
        with patch("xpra.net.quic.congestion.monotonic", side_effect=lambda: self.now), \
                patch("xpra.net.quic.connection.get_threaded_loop", return_value=ImmediateLoop()):
            self.client.connect(ADDR, now=self.now)
            for _ in range(5000):
                self.tick(impairment=False)
                if self.client._handshake_complete and self.server._handshake_complete:
                    break
            else:
                raise RuntimeError("handshake failed")
            self.http[0].send_headers(0, [(b":method", b"CONNECT"), (b":protocol", b"websocket"),
                                          (b":scheme", b"https"), (b":authority", b"localhost"), (b":path", b"/")])
            for _ in range(5000):
                self.tick(impairment=False)
                if self.connected:
                    break
            else:
                raise RuntimeError("HTTP/3 CONNECT failed")
            self.origin = self.now
            next_frame = next_audio = next_sample = 0.0
            while self.now - self.origin < self.duration:
                elapsed = self.now - self.origin
                if elapsed >= next_frame:
                    if self.name != "sparse" or elapsed < 12:
                        self.send_frame()
                    next_frame += 2 if self.name == "sparse" else 1 / 30
                if self.name == "audio" and elapsed >= next_audio:
                    self.send_audio()
                    next_audio += 0.02
                self.tick()
                if self.now - self.origin >= next_sample:
                    self.sample()
                    next_sample += SAMPLE_PERIOD
            for _ in range(120_000):
                pending = any("acked" not in f for f in self.frame_records)
                queued = any(q._datagrams_pending or any(len(s.sender._pending) for s in q._streams.values()) for q in self.quics)
                in_flight = any(q._loss.bytes_in_flight for q in self.quics)
                if not pending and not queued and not in_flight and not self.events:
                    break
                self.tick()
            else:
                raise RuntimeError(f"{self.name}/{self.seed}: failed to drain")
            last_loss = self.connections[1].congestion_control.get_info().get("last-loss-age-ms")
            self.now += 1.2
            idle = self.connections[1].congestion_control.get_info()
            assert idle["recent"]["status"] == "idle", idle
            assert "acked-bitrate" not in idle["recent"], idle
            if last_loss is not None:
                assert idle["last-loss-age-ms"] >= last_loss + 1199
        assert all("acked" in f for f in self.frame_records)
        return self.summarize()

    def summarize(self):
        phases = []
        start = 0.0
        for phase in self.phases:
            stop = start + phase.seconds
            warmup = min(3.0, phase.seconds / 4)
            rows = [r for r in self.traces if start + warmup <= r["time"] < stop]
            acked = [f for f in self.frame_records if start + warmup <= f.get("acked", -1) < stop]
            audio = [f for f in self.audio_records if start + warmup <= f.get("received", -1) < stop]
            errors = [abs(r["acked-bps"] - r["exact-acked-bps"]) / r["exact-acked-bps"] for r in rows
                      if r["acked-bps"] is not None and r["exact-acked-bps"] > 0]
            phases.append({
                "phase": phase.name, "mbps": phase.mbps, "base-rtt-ms": 2 * phase.delay_ms,
                "acked-mbps-median": statistics.median([r["acked-bps"] / 1e6 for r in rows if r["acked-bps"] is not None])
                if any(r["acked-bps"] is not None for r in rows) else None,
                "rtt-ms-median": statistics.median(r["rtt-ms"] for r in rows),
                "rtt-trend-ms-min": min((r["rtt-trend-ms"] for r in rows if r["rtt-trend-ms"] is not None), default=None),
                "rtt-trend-ms-max": max((r["rtt-trend-ms"] for r in rows if r["rtt-trend-ms"] is not None), default=None),
                "loss-pct-median": percentile([100 * r["loss-fraction"] for r in rows if r["loss-fraction"] is not None], 0.5),
                "cwnd-KB-median": statistics.median(r["cwnd"] / 1000 for r in rows),
                "cwnd-rate-mbps-median": statistics.median(r["cwnd-rate-mbps"] for r in rows),
                "pending-KB-max": max(r["pending-bytes"] / 1000 for r in rows),
                "oldest-unacked-ms-max": max(r["oldest-unacked-ms"] for r in rows),
                "frame-ack-ms-p50": percentile([(f["acked"] - f["sent"]) * 1000 for f in acked], 0.5),
                "frame-ack-ms-p95": percentile([(f["acked"] - f["sent"]) * 1000 for f in acked], 0.95),
                "audio-latency-ms-p95": percentile([(f["received"] - f["sent"]) * 1000 for f in audio], 0.95),
                "reported-rate-error-p50-pct": percentile([100 * e for e in errors], 0.5),
                "reported-rate-error-max-pct": max(errors) * 100 if errors else None,
                "statuses": {status: sum(r["status"] == status for r in rows) for status in ("active", "idle", "insufficient")},
            })
            start = stop
        return {
            "scenario": self.name, "seed": self.seed, "phases": phases,
            "frames": len(self.frame_records), "frames-acked": sum("acked" in f for f in self.frame_records),
            "audio-sent": len(self.audio_records), "audio-received": sum("received" in f for f in self.audio_records),
            "decode-cpu-ms-p50": percentile(self.decode_costs, 0.5),
            "decode-cpu-ms-p95": percentile(self.decode_costs, 0.95),
            "drops": [{"sent": d.sent, "random": d.random_drops, "queue": d.queue_drops, "burst": d.burst_drops}
                      for d in self.links],
            "drain-seconds": self.now - self.origin - self.duration - 1.2,
            "idle-expiry-passed": True,
        }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("/tmp/xpra-quic-4202"))
    parser.add_argument("--seeds", type=int, nargs="+", default=[1, 2, 3])
    parser.add_argument("--scenarios", nargs="+", choices=SCENARIOS, default=list(SCENARIOS))
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    cert, key = certificate()
    frames = jpeg_frames()
    started = perf_counter()
    results = []
    for scenario in args.scenarios:
        for seed in args.seeds:
            experiment = Experiment(scenario, seed, cert, key, frames)
            result = experiment.run()
            results.append(result)
            with (args.output / f"{scenario}-{seed}.csv").open("w", newline="") as output:
                writer = csv.DictWriter(output, fieldnames=experiment.traces[0])
                writer.writeheader()
                writer.writerows(experiment.traces)
            print(json.dumps(result), flush=True)
    document = {
        "revision": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
        "python": platform.python_version(), "aioquic": aioquic.__version__, "pillow": Image.__version__,
        "jpeg-bytes-mean": statistics.mean(map(len, frames)),
        "offered-jpeg-mbps": statistics.mean(map(len, frames)) * 30 * 8 / 1e6,
        "wall-seconds": perf_counter() - started, "results": results,
    }
    (args.output / "results.json").write_text(json.dumps(document, indent=2) + "\n")


if __name__ == "__main__":
    main()
