# This file is part of Xpra.
# Copyright (C) 2011 Serviware (Arthur Huillet, <ahuillet@serviware.com>)
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from math import sqrt
from time import monotonic
from typing import Deque, Any

from collections import deque
from xpra.util.stats import get_list_stats, get_weighted_list_stats
from xpra.util.str_fn import csv
from xpra.util.env import envint
from xpra.server.cystats import (
    logp,
    calculate_time_weighted_average,
    calculate_size_weighted_average,
    calculate_timesize_weighted_average,
    calculate_for_average,
)

from xpra.log import Logger

log = Logger("stats")

# how many historical records to keep
# for the various statistics we collect:
# (cannot be lower than DamageBatchConfig.max_events)
NRECS: int = 100

TARGET_LATENCY_TOLERANCE = envint("XPRA_TARGET_LATENCY_TOLERANCE", 20) / 1000.0


class WindowPerformanceStatistics:
    """
    Statistics which belong to a specific WindowSource
    """

    def __init__(self):
        self.reset()

    # assume 100ms until we get some data to compute the real values
    DEFAULT_DAMAGE_LATENCY: float = 0.1
    DEFAULT_NETWORK_LATENCY: float = 0.1
    DEFAULT_TARGET_LATENCY: float = 0.1

    def reset(self) -> None:
        self.init_time: float = monotonic()
        # records how long it took the client to decode frames:
        # (ack_time, no of pixels, decoding_time*1000*1000)
        self.client_decode_time: Deque[tuple[float, int, int]] = deque(maxlen=NRECS)
        # encoding: (time, coding, pixels, bpp, compressed_size, encoding_time)
        self.encoding_stats: Deque[tuple[float, str, int, int, int, float]] = deque(maxlen=NRECS)
        # records how long it took for a damage request to be sent
        # last NRECS: (sent_time, no of pixels, actual batch delay, damage_latency)
        self.damage_in_latency: Deque[tuple[float, int, float, float]] = deque(maxlen=NRECS)
        # records how long it took for a damage request to be processed
        # last NRECS: (processed_time, no of pixels, actual batch delay, damage_latency)
        self.damage_out_latency: Deque[tuple[float, int, float, float]] = deque(maxlen=NRECS)
        # records when damage packets are sent,
        # so we can calculate the "client_latency" when the client sends
        # the corresponding ack ("damage-sequence" packet - see "client_ack_damage")
        self.damage_ack_pending: dict[int, tuple[float, str, int, int, dict, float]] = {}
        # for each encoding, how many frames we sent and how many pixels in total
        self.encoding_totals: dict[str, list[int]] = {}
        # damage regions waiting to be picked up by the encoding thread:
        # for each sequence no: (damage_time, w, h)
        self.encoding_pending: dict = {}
        # every time we get a damage event, we record: time,x,y,w,h
        self.last_damage_events: Deque[tuple[float, int, int, int, int]] = deque(maxlen=4 * NRECS)
        self.last_damage_event_time: float = 0
        self.last_recalculate: float = 0
        self.damage_events_count = 0
        self.packet_count = 0

        self.resize_events: Deque[float] = deque(maxlen=4)  # (time)
        self.last_resized: float = 0
        self.last_packet_time: float = 0

        # these values are calculated from the values above (see update_averages)
        self.target_latency = self.DEFAULT_TARGET_LATENCY
        self.avg_damage_in_latency = self.DEFAULT_DAMAGE_LATENCY
        self.recent_damage_in_latency = self.DEFAULT_DAMAGE_LATENCY
        self.avg_damage_out_latency = self.DEFAULT_DAMAGE_LATENCY + self.DEFAULT_NETWORK_LATENCY
        self.recent_damage_out_latency = self.DEFAULT_DAMAGE_LATENCY + self.DEFAULT_NETWORK_LATENCY
        self.max_latency = self.DEFAULT_DAMAGE_LATENCY + self.DEFAULT_NETWORK_LATENCY
        self.avg_decode_speed = -1
        self.recent_decode_speed = -1

    def reset_backlog(self) -> None:
        # this should be a last resort..
        self.damage_ack_pending = {}

    def update_averages(self) -> None:
        # damage "in" latency: (the time it takes for damage requests to be processed only)
        dil = tuple(self.damage_in_latency)
        if dil:
            data = tuple((when, latency) for when, _, _, latency in dil)
            self.avg_damage_in_latency, self.recent_damage_in_latency = calculate_time_weighted_average(data)
        # damage "out" latency: (the time it takes for damage requests to be processed and sent out)
        dol = tuple(self.damage_out_latency)
        if dol:
            data = tuple((when, latency) for when, _, _, latency in dol)
            self.avg_damage_out_latency, self.recent_damage_out_latency = calculate_time_weighted_average(data)
        # client decode speed:
        cdt = tuple(self.client_decode_time)
        if cdt:
            # the elapsed time recorded is in microseconds:
            decode_speed = tuple(
                (event_time, size, int(size * 1000 * 1000 / elapsed))
                for event_time, size, elapsed in cdt if elapsed > 0
            )
            r = calculate_size_weighted_average(decode_speed)
            self.avg_decode_speed = int(r[0])
            self.recent_decode_speed = int(r[1])
        # network send speed:
        all_l = [0.1,
                 self.avg_damage_in_latency, self.recent_damage_in_latency,
                 self.avg_damage_out_latency, self.recent_damage_out_latency]
        self.max_latency = max(all_l)

    def get_factors(self, bandwidth_limit=0) -> list[tuple[str, str, float, float]]:
        factors = []

        def mayaddfac(metric, info, factor, weight):
            if weight > 0.01:
                factors.append((metric, info, factor, weight))

        # ratio of "in" and "out" latency indicates network bottleneck:
        # (the difference between the two is the time it takes to send)
        if self.damage_in_latency and self.damage_out_latency:
            # prevent jitter from skewing the values too much
            ad = max(0.010, 0.040 + self.avg_damage_out_latency - self.avg_damage_in_latency)
            rd = max(0.010, 0.040 + self.recent_damage_out_latency - self.recent_damage_in_latency)
            metric = "damage-network-delay"
            # info: avg delay=%.3f recent delay=%.3f" % (ad, rd)
            mayaddfac(*calculate_for_average(metric, ad, rd))
        # client decode time:
        ads = self.avg_decode_speed
        rds = self.recent_decode_speed
        if ads > 0 and rds > 0:
            metric = "client-decode-speed"
            # info: avg=%.1f, recent=%.1f (MPixels/s)" % (ads/1000/1000, self.recent_decode_speed/1000/1000)
            # our calculate methods aims for lower values, so invert speed
            # this is how long it takes to send 1MB:
            avg1MB = 1.0 * 1024 * 1024 / ads
            recent1MB = 1.0 * 1024 * 1024 / rds
            weight_div = max(0.25, rds / (4 * 1000 * 1000))
            mayaddfac(*calculate_for_average(metric, avg1MB, recent1MB, weight_offset=0.0, weight_div=weight_div))
        ldet = self.last_damage_event_time
        if ldet:
            # If nothing happens for a while then we can reduce the batch delay,
            # however we must ensure this is not caused by a high system latency,
            # so we ignore short elapsed times.
            elapsed = monotonic() - ldet
            mtime = max(0.0, elapsed - self.max_latency * 2)
            # the longer the time, the more we slash:
            weight = sqrt(mtime)
            target = max(0.0, 1.0 - mtime)
            metric = "damage-rate"
            info = {"elapsed": int(1000.0 * elapsed),
                    "max_latency": int(1000.0 * self.max_latency)}
            mayaddfac(metric, info, target, weight)
        if bandwidth_limit > 0:
            # calculate how much bandwidth we have used in the last second (in bps):
            # encoding_stats.append((end, coding, w*h, bpp, len(data), end-start))
            cutoff = monotonic() - 1
            used = sum(v[4] for v in tuple(self.encoding_stats) if v[0] > cutoff) * 8
            info = {
                "budget": bandwidth_limit,
                "used": used,
            }
            # aim for 10% below the limit:
            target = used * 110.0 / 100.0 / bandwidth_limit
            # if we are getting close to or above the limit,
            # the certainty of this factor goes up:
            weight = max(0.0, target - 1) * (5 + logp(target))
            mayaddfac("bandwidth-limit", info, target, weight)
        return factors

    def get_info(self) -> dict[str, Any]:
        info = {
            "damage": {
                "events": self.damage_events_count,
                "packets_sent": self.packet_count,
                "target-latency": int(1000 * self.target_latency),
            }
        }
        # encoding stats:
        estats = tuple(self.encoding_stats)
        if estats:
            def add_compression_stats(enc_stats, encoding=None):
                comp_ratios_pct = []
                comp_times_ns = []
                total_pixels = 0
                total_time = 0.0
                for _, _, pixels, bpp, compressed_size, compression_time in enc_stats:
                    if compressed_size > 0 and pixels > 0:
                        osize = pixels * bpp / 8
                        comp_ratios_pct.append((100.0 * compressed_size / osize, pixels))
                        comp_times_ns.append((1000.0 * 1000 * 1000 * compression_time / pixels, pixels))
                        total_pixels += pixels
                        total_time += compression_time
                einfo: dict[str, Any] = info.setdefault(encoding or "encoding", {})
                einfo["ratio_pct"] = get_weighted_list_stats(comp_ratios_pct)
                einfo["pixels_per_ns"] = get_weighted_list_stats(comp_times_ns)
                if total_time > 0:
                    einfo["pixels_encoded_per_second"] = int(total_pixels / total_time)

            add_compression_stats(estats)
            encodings_used = tuple(x[1] for x in estats)
            for encoding in encodings_used:
                enc_stats = tuple(x for x in estats if x[1] == encoding)
                add_compression_stats(enc_stats, encoding)

        dinfo = info.setdefault("damage", {})
        latencies = tuple(x[-1] * 1000 for x in tuple(self.damage_in_latency))
        dinfo["in_latency"] = get_list_stats(latencies, show_percentile=(9,))
        latencies = tuple(x[-1] * 1000 for x in tuple(self.damage_out_latency))
        dinfo["out_latency"] = get_list_stats(latencies, show_percentile=(9,))
        # per encoding totals:
        if self.encoding_totals:
            tf = info.setdefault("total_frames", {})
            tp = info.setdefault("total_pixels", {})
            for encoding, totals in tuple(self.encoding_totals.items()):
                tf[encoding] = totals[0]
                tp[encoding] = totals[1]
        return info

    def get_target_client_latency(self, min_client_latency, avg_client_latency, abs_min=0.010, jitter=0) -> float:
        """ geometric mean of the minimum (+20%) and average latency
            but not higher than twice more than the minimum,
            and not lower than abs_min.
            Then we add the average decoding latency.
            """
        decoding_latency = 0.010
        cdt = tuple(self.client_decode_time)
        if cdt:
            decoding_latency = calculate_timesize_weighted_average(cdt)[0] / 1000.0
        min_latency = max(abs_min, min_client_latency or abs_min) * 1.2
        avg_latency = max(min_latency, avg_client_latency or abs_min)
        max_latency = min(avg_latency, 4.0 * min_latency + 0.100)
        return max(abs_min, min(max_latency, sqrt(min_latency * avg_latency))) + decoding_latency + jitter / 1000.0

    def get_client_backlog(self) -> tuple[int, int]:
        packets_backlog, pixels_backlog = 0, 0
        if self.damage_ack_pending:
            queued_before = monotonic() - (self.target_latency + TARGET_LATENCY_TOLERANCE)
            dropped_acks_time = monotonic() - 60  # 1 minute
            drop_missing_acks = []
            for sequence, item in tuple(self.damage_ack_pending.items()):
                queued_at = item[0]
                if queued_at > queued_before:
                    continue
                if queued_at < dropped_acks_time:
                    drop_missing_acks.append(sequence)
                else:
                    # ack_pending = (now, coding, pixcount, bytecount, client_options, damage_time)
                    pixels = item[2]
                    packets_backlog += 1
                    pixels_backlog += pixels
            log("get_client_backlog missing acks: %s", drop_missing_acks)
            # this should never happen...
            if drop_missing_acks:
                log.error("Error: expiring %i missing damage ACKs,", len(drop_missing_acks))
                log.error(" connection may be closed or closing,")
                log.error(" sequence numbers missing: %s", csv(drop_missing_acks))
                for sequence in drop_missing_acks:
                    self.damage_ack_pending.pop(sequence, None)
        return packets_backlog, pixels_backlog

    def get_acks_pending(self) -> int:
        return sum(1 for x in self.damage_ack_pending.values() if x[0] != 0)

    def get_late_acks(self, latency) -> int:
        now = monotonic()
        sent_before = now - latency
        late = sum(1 for item in self.damage_ack_pending.values() if item[0] <= sent_before)
        log("get_late_acks(%i)=%i (%i in full pending list)", 1000 * latency, late, len(self.damage_ack_pending))
        return late

    def get_pixels_encoding_backlog(self) -> tuple[int, int]:
        pixels, count = 0, 0
        for _, w, h in self.encoding_pending.values():
            pixels += w * h
            count += 1
        return pixels, count

    def get_bitrate(self, max_elapsed: float = 1) -> int:
        cutoff = monotonic() - max_elapsed
        recs = tuple((v[0], v[4]) for v in tuple(self.encoding_stats) if v[0] >= cutoff)
        if len(recs) < 2:
            return 0
        bits = sum(v[1] for v in recs) * 8
        elapsed = recs[-1][0] - recs[0][0]
        if elapsed == 0:
            return 0
        return int(bits / elapsed)

    def get_damage_pixels(self, elapsed: float = 1) -> int:
        cutoff = monotonic() - elapsed
        return sum(v[3] * v[4] for v in tuple(self.last_damage_events) if v[0] > cutoff)
