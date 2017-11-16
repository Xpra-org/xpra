# -*- coding: utf-8 -*-
# This file is part of Xpra.
# Copyright (C) 2011 Serviware (Arthur Huillet, <ahuillet@serviware.com>)
# Copyright (C) 2010-2017 Antoine Martin <antoine@devloop.org.uk>
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.


#how many historical records to keep
#for the various statistics we collect:
#(cannot be lower than DamageBatchConfig.MAX_EVENTS)
NRECS = 100

from math import sqrt

from xpra.log import Logger
log = Logger("stats")

from collections import deque
from xpra.simple_stats import get_list_stats, get_weighted_list_stats
from xpra.os_util import monotonic_time
from xpra.util import engs, csv, envint
from xpra.server.cystats import (logp,      #@UnresolvedImport
    calculate_time_weighted_average,        #@UnresolvedImport
    calculate_timesize_weighted_average,    #@UnresolvedImport
    calculate_for_average)                  #@UnresolvedImport


TARGET_LATENCY_TOLERANCE = envint("XPRA_TARGET_LATENCY_TOLERANCE", 20)/1000.0


class WindowPerformanceStatistics(object):
    """
    Statistics which belong to a specific WindowSource
    """
    def __init__(self):
        self.reset()

    #assume 100ms until we get some data to compute the real values
    DEFAULT_DAMAGE_LATENCY = 0.1
    DEFAULT_NETWORK_LATENCY = 0.1
    DEFAULT_TARGET_LATENCY = 0.1

    def reset(self):
        self.client_decode_time = deque(maxlen=NRECS)       #records how long it took the client to decode frames:
                                                            #(ack_time, no of pixels, decoding_time*1000*1000)
        self.encoding_stats = deque(maxlen=NRECS)           #encoding: (time, coding, pixels, bpp, compressed_size, encoding_time)
        # statistics:
        self.damage_in_latency = deque(maxlen=NRECS)        #records how long it took for a damage request to be sent
                                                            #last NRECS: (sent_time, no of pixels, actual batch delay, damage_latency)
        self.damage_out_latency = deque(maxlen=NRECS)       #records how long it took for a damage request to be processed
                                                            #last NRECS: (processed_time, no of pixels, actual batch delay, damage_latency)
        self.damage_ack_pending = {}                        #records when damage packets are sent
                                                            #so we can calculate the "client_latency" when the client sends
                                                            #the corresponding ack ("damage-sequence" packet - see "client_ack_damage")
        self.encoding_totals = {}                           #for each encoding, how many frames we sent and how many pixels in total
        self.encoding_pending = {}                          #damage regions waiting to be picked up by the encoding thread:
                                                            #for each sequence no: (damage_time, w, h)
        self.last_damage_events = deque(maxlen=4*NRECS)     #every time we get a damage event, we record: time,x,y,w,h
        self.last_damage_event_time = None
        self.last_recalculate = 0
        self.damage_events_count = 0
        self.packet_count = 0

        self.last_resized = 0

        #these values are calculated from the values above (see update_averages)
        self.target_latency = self.DEFAULT_TARGET_LATENCY
        self.avg_damage_in_latency = self.DEFAULT_DAMAGE_LATENCY
        self.recent_damage_in_latency = self.DEFAULT_DAMAGE_LATENCY
        self.avg_damage_out_latency = self.DEFAULT_DAMAGE_LATENCY + self.DEFAULT_NETWORK_LATENCY
        self.recent_damage_out_latency = self.DEFAULT_DAMAGE_LATENCY + self.DEFAULT_NETWORK_LATENCY
        self.max_latency = self.DEFAULT_DAMAGE_LATENCY + self.DEFAULT_NETWORK_LATENCY
        self.avg_decode_speed = -1
        self.recent_decode_speed = -1

    def update_averages(self):
        #damage "in" latency: (the time it takes for damage requests to be processed only)
        if len(self.damage_in_latency)>0:
            data = [(when, latency) for when, _, _, latency in list(self.damage_in_latency)]
            self.avg_damage_in_latency, self.recent_damage_in_latency =  calculate_time_weighted_average(data)
        #damage "out" latency: (the time it takes for damage requests to be processed and sent out)
        if len(self.damage_out_latency)>0:
            data = [(when, latency) for when, _, _, latency in list(self.damage_out_latency)]
            self.avg_damage_out_latency, self.recent_damage_out_latency = calculate_time_weighted_average(data)
        #client decode speed:
        if len(self.client_decode_time)>0:
            #the elapsed time recorded is in microseconds, so multiply by 1000*1000 to get the real value:
            self.avg_decode_speed, self.recent_decode_speed = calculate_timesize_weighted_average(list(self.client_decode_time), sizeunit=1000*1000)
        #network send speed:
        all_l = [0.1,
                 self.avg_damage_in_latency, self.recent_damage_in_latency,
                 self.avg_damage_out_latency, self.recent_damage_out_latency]
        self.max_latency = max(all_l)

    def get_factors(self, bandwidth_limit=0):
        factors = []
        #ratio of "in" and "out" latency indicates network bottleneck:
        #(the difference between the two is the time it takes to send)
        if len(self.damage_in_latency)>0 and len(self.damage_out_latency)>0:
            #prevent jitter from skewing the values too much
            ad = max(0.010, 0.040+self.avg_damage_out_latency-self.avg_damage_in_latency)
            rd = max(0.010, 0.040+self.recent_damage_out_latency-self.recent_damage_in_latency)
            metric = "damage-network-delay"
            #info: avg delay=%.3f recent delay=%.3f" % (ad, rd)
            factors.append(calculate_for_average(metric, ad, rd))
        #client decode time:
        ads = self.avg_decode_speed
        rds = self.recent_decode_speed
        if ads>0 and rds>0:
            metric = "client-decode-speed"
            #info: avg=%.1f, recent=%.1f (MPixels/s)" % (ads/1000/1000, self.recent_decode_speed/1000/1000)
            #our calculate methods aims for lower values, so invert speed
            #this is how long it takes to send 1MB:
            avg1MB = 1.0*1024*1024/ads
            recent1MB = 1.0*1024*1024/rds
            weight_div = max(0.25, rds/(4*1000*1000))
            factors.append(calculate_for_average(metric, avg1MB, recent1MB, weight_offset=0.0, weight_div=weight_div))
        ldet = self.last_damage_event_time
        if ldet:
            #If nothing happens for a while then we can reduce the batch delay,
            #however we must ensure this is not caused by a high system latency
            #so we ignore short elapsed times.
            elapsed = monotonic_time()-ldet
            mtime = max(0, elapsed-self.max_latency*2)
            #the longer the time, the more we slash:
            weight = sqrt(mtime)
            target = max(0, 1.0-mtime)
            metric = "damage-rate"
            info = {"elapsed"   : int(1000.0*elapsed),
                    "max_latency"   : int(1000.0*self.max_latency)}
            factors.append((metric, info, target, weight))
        if bandwidth_limit>0:
            #calculate how much bandwith we have used in the last second (in bps):
            #encoding_stats.append((end, coding, w*h, bpp, len(data), end-start))
            cutoff = monotonic_time()-1
            used = sum(v[4] for v in self.encoding_stats if v[0]>cutoff) * 8
            info = {
                "bandwidth-limit"   : bandwidth_limit,
                "bandwidth-used"    : used,
                }
            #aim for 10% below the limit:
            target = used*110.0/100.0/bandwidth_limit
            #if we are getting close to or above the limit,
            #the certainty of this factor goes up:
            weight = max(0, target-1)*(5+logp(target))
            factors.append(("bandwidth-limit", info, target, weight))
        return factors


    def get_info(self):
        info = {"damage"    : {"events"         : self.damage_events_count,
                               "packets_sent"   : self.packet_count,
                               "target-latency" : int(1000*self.target_latency),
                               }
                }
        #encoding stats:
        if len(self.encoding_stats)>0:
            estats = list(self.encoding_stats)
            encodings_used = [x[1] for x in estats]
            def add_compression_stats(enc_stats, encoding=None):
                comp_ratios_pct = []
                comp_times_ns = []
                total_pixels = 0
                total_time = 0.0
                for _, _, pixels, bpp, compressed_size, compression_time in enc_stats:
                    if compressed_size>0 and pixels>0:
                        osize = pixels*bpp/8
                        comp_ratios_pct.append((100.0*compressed_size/osize, pixels))
                        comp_times_ns.append((1000.0*1000*1000*compression_time/pixels, pixels))
                        total_pixels += pixels
                        total_time += compression_time
                einfo = info.setdefault("encoding", {})
                if encoding:
                    einfo = einfo.setdefault(encoding, {})
                einfo["ratio_pct"] = get_weighted_list_stats(comp_ratios_pct)
                einfo["pixels_per_ns"] = get_weighted_list_stats(comp_times_ns)
                if total_time>0:
                    einfo["pixels_encoded_per_second"] = int(total_pixels / total_time)
            add_compression_stats(estats)
            for encoding in encodings_used:
                enc_stats = [x for x in estats if x[1]==encoding]
                add_compression_stats(enc_stats, encoding)

        dinfo = info.setdefault("damage", {})
        latencies = [x*1000 for _, _, _, x in list(self.damage_in_latency)]
        dinfo["in_latency"]  = get_list_stats(latencies, show_percentile=[9])
        latencies = [x*1000 for _, _, _, x in list(self.damage_out_latency)]
        dinfo["out_latency"] = get_list_stats(latencies, show_percentile=[9])
        #per encoding totals:
        if self.encoding_totals:
            tf = info.setdefault("total_frames", {})
            tp = info.setdefault("total_pixels", {})
        for encoding, totals in self.encoding_totals.items():
            tf[encoding] = totals[0]
            tp[encoding] = totals[1]
        return info


    def get_target_client_latency(self, min_client_latency, avg_client_latency, abs_min=0.010):
        """ geometric mean of the minimum (+20%) and average latency
            but not higher than twice more than the minimum,
            and not lower than abs_min.
            Then we add the average decoding latency.
            """
        decoding_latency = 0.010
        if len(self.client_decode_time)>0:
            decoding_latency, _ = calculate_timesize_weighted_average(list(self.client_decode_time))
            decoding_latency /= 1000.0
        min_latency = max(abs_min, min_client_latency or abs_min)*1.2
        avg_latency = max(min_latency, avg_client_latency or abs_min)
        max_latency = 2.0*min_latency
        return max(abs_min, min(max_latency, sqrt(min_latency*avg_latency))) + decoding_latency

    def get_client_backlog(self):
        packets_backlog, pixels_backlog, bytes_backlog = 0, 0, 0
        if len(self.damage_ack_pending)>0:
            sent_before = monotonic_time()-(self.target_latency+TARGET_LATENCY_TOLERANCE)
            dropped_acks_time = monotonic_time()-60      #1 minute
            drop_missing_acks = []
            for sequence, (start_send_at, _, start_bytes, end_send_at, end_bytes, pixels) in self.damage_ack_pending.items():
                if end_send_at==0 or start_send_at>sent_before:
                    continue
                if start_send_at<dropped_acks_time:
                    drop_missing_acks.append(sequence)
                else:
                    packets_backlog += 1
                    pixels_backlog += pixels
                    bytes_backlog += (end_bytes - start_bytes)
            log("get_client_backlog missing acks: %s", drop_missing_acks)
            #this should never happen...
            if len(drop_missing_acks)>0:
                log.error("Error: expiring %i missing damage ACK%s,", len(drop_missing_acks), engs(drop_missing_acks))
                log.error(" connection may be closed or closing,")
                log.error(" sequence numbers missing: %s", csv(drop_missing_acks))
                for sequence in drop_missing_acks:
                    try:
                        del self.damage_ack_pending[sequence]
                    except:
                        pass
        return packets_backlog, pixels_backlog, bytes_backlog

    def get_acks_pending(self):
        return len(self.damage_ack_pending)

    def get_packets_backlog(self):
        packets_backlog = 0
        if len(self.damage_ack_pending)>0:
            sent_before = monotonic_time()-(self.target_latency+0.020)
            for _, (start_send_at, _, _, end_send_at, _, _) in self.damage_ack_pending.items():
                if end_send_at>0 and start_send_at<=sent_before:
                    packets_backlog += 1
        return packets_backlog

    def get_pixels_encoding_backlog(self):
        pixels, count = 0, 0
        for _, w, h in self.encoding_pending.values():
            pixels += w*h
            count += 1
        return pixels, count

    def get_bits_encoded(self, elapsed=1):
        cutoff = monotonic_time()-elapsed
        return sum(v[4] for v in self.encoding_stats if v[0]>cutoff) * 8

    def get_damage_pixels(self, elapsed=1):
        cutoff = monotonic_time()-elapsed
        return sum(v[3]*v[4] for v in self.last_damage_events if v[0]>cutoff)
