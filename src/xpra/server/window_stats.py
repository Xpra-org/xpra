# coding=utf8
# This file is part of Xpra.
# Copyright (C) 2011 Serviware (Arthur Huillet, <ahuillet@serviware.com>)
# Copyright (C) 2010-2013 Antoine Martin <antoine@devloop.org.uk>
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.


#how many historical records to keep
#for the various statistics we collect:
#(cannot be lower than DamageBatchConfig.MAX_EVENTS)
NRECS = 100

import time
from math import sqrt

from xpra.log import Logger
log = Logger()

from xpra.deque import maxdeque
from xpra.simple_stats import add_list_stats, add_weighted_list_stats
from xpra.server.stats.maths import logp, \
    calculate_time_weighted_average, calculate_timesize_weighted_average, \
    calculate_for_target, calculate_for_average


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
        self.client_decode_time = maxdeque(NRECS)       #records how long it took the client to decode frames:
                                                        #(ack_time, no of pixels, decoding_time*1000*1000)
        self.encoding_stats = maxdeque(NRECS)           #encoding: (coding, pixels, compressed_size, encoding_time)
        # statistics:
        self.damage_in_latency = maxdeque(NRECS)        #records how long it took for a damage request to be sent
                                                        #last NRECS: (sent_time, no of pixels, actual batch delay, damage_latency)
        self.damage_out_latency = maxdeque(NRECS)       #records how long it took for a damage request to be processed
                                                        #last NRECS: (processed_time, no of pixels, actual batch delay, damage_latency)
        self.damage_send_speed = maxdeque(NRECS)        #how long it took to send damage packets (this is not a sustained speed)
                                                        #last NRECS: (sent_time, no_of_pixels, elapsed_time)
        self.damage_ack_pending = {}                    #records when damage packets are sent
                                                        #so we can calculate the "client_latency" when the client sends
                                                        #the corresponding ack ("damage-sequence" packet - see "client_ack_damage")
        self.encoding_totals = {}                       #for each encoding, how many frames we sent and how many pixels in total
        self.last_damage_event_time = None
        self.damage_events_count = 0
        self.packet_count = 0

        #these values are calculated from the values above (see update_averages)
        self.target_latency = self.DEFAULT_TARGET_LATENCY
        self.avg_damage_in_latency = self.DEFAULT_DAMAGE_LATENCY
        self.recent_damage_in_latency = self.DEFAULT_DAMAGE_LATENCY
        self.avg_damage_out_latency = self.DEFAULT_DAMAGE_LATENCY + self.DEFAULT_NETWORK_LATENCY
        self.recent_damage_out_latency = self.DEFAULT_DAMAGE_LATENCY + self.DEFAULT_NETWORK_LATENCY
        self.max_latency = self.DEFAULT_DAMAGE_LATENCY + self.DEFAULT_NETWORK_LATENCY
        self.avg_decode_speed = None
        self.recent_decode_speed = None
        self.avg_send_speed = None
        self.recent_send_speed = None

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
        if len(self.damage_send_speed)>0:
            self.avg_send_speed, self.recent_send_speed = calculate_timesize_weighted_average(list(self.damage_send_speed))
        all_l = [0.1,
                 self.avg_damage_in_latency, self.recent_damage_in_latency,
                 self.avg_damage_out_latency, self.recent_damage_out_latency]
        self.max_latency = max(all_l)

    def get_factors(self, pixel_count, delay):
        factors = []
        #damage "in" latency factors:
        if len(self.damage_in_latency)>0:
            metric = "damage-processing-latency"
            target_latency = 0.010 + (0.050*pixel_count/1024.0/1024.0)
            factors.append(calculate_for_target(metric, target_latency, self.avg_damage_in_latency, self.recent_damage_in_latency, aim=0.8, slope=0.005, smoothing=sqrt))
            #ratio to delay (aim for double the latency so we always have packets in flight):
            metric = "damage-processing-ratios"
            md = 1.5 * max(0.005, delay / 1000.0)
            fa = sqrt(self.avg_damage_in_latency / md)
            fr = sqrt(self.recent_damage_in_latency / md)
            weight = max(abs(fa-1.0), abs(fr-1.0))
            info = {
                    "avg_damage_in_latency" : int(1000.0*self.avg_damage_in_latency),
                    "recent_damage_in_latency"  : int(1000.0*self.recent_damage_in_latency),
                    "delay" : int(delay),
                    "avg_factor"    : int(1000.0*fa),
                    "recent_factor" : int(1000.0*fr)
                    }
            factors.append((metric, info, (fa+fr*2)/3.0, weight))
        #damage "out" latency
        if len(self.damage_out_latency)>0:
            metric = "damage-out-latency"
            target_latency = 0.025 + (0.060*pixel_count/1024.0/1024.0)
            factors.append(calculate_for_target(metric, target_latency, self.avg_damage_out_latency, self.recent_damage_out_latency, aim=0.8, slope=0.010, smoothing=sqrt))
        #ratio of "in" and "out" latency indicates network bottleneck:
        if len(self.damage_in_latency)>0 and len(self.damage_out_latency)>0:
            ad = max(0.001, self.avg_damage_out_latency-self.avg_damage_in_latency)
            rd = max(0.001, self.recent_damage_out_latency-self.recent_damage_in_latency)
            div = 0.040 / max(ad, rd)       #reduce weight for low latencies (matter less)
            metric = "damage-network-delay"
            #info: avg delay=%.3f recent delay=%.3f" % (ad, rd)
            factors.append(calculate_for_average(metric, ad, rd, weight_div=div))
        #send speed:
        if self.avg_send_speed is not None and self.recent_send_speed is not None:
            #our calculate methods aims for lower values, so invert speed
            #this is how long it takes to send 1MB:
            avg1MB = 1.0*1024*1024/self.avg_send_speed
            recent1MB = 1.0*1024*1024/self.recent_send_speed
            #we only really care about this when the speed is quite low,
            #so adjust the weight accordingly:
            minspeed = float(128*1024)
            div = logp(max(self.recent_send_speed, minspeed)/minspeed)
            metric = "network-send-speed"
            #info: avg=%s, recent=%s (KBytes/s), div=%s" % (int(self.avg_send_speed/1024), int(self.recent_send_speed/1024), div)
            factors.append(calculate_for_average(metric, avg1MB, recent1MB, weight_offset=1.0, weight_div=div))
        #client decode time:
        if self.avg_decode_speed is not None and self.recent_decode_speed is not None:
            metric = "client-decode-speed"
            #info: avg=%.1f, recent=%.1f (MPixels/s)" % (self.avg_decode_speed/1000/1000, self.recent_decode_speed/1000/1000)
            #our calculate methods aims for lower values, so invert speed
            #this is how long it takes to send 1MB:
            avg1MB = 1.0*1024*1024/self.avg_decode_speed
            recent1MB = 1.0*1024*1024/self.recent_decode_speed
            weight_div = max(0.25, self.recent_decode_speed/(4*1000*1000))
            factors.append(calculate_for_average(metric, avg1MB, recent1MB, weight_offset=0.0, weight_div=weight_div))
        if self.last_damage_event_time:
            #If nothing happens for a while then we can reduce the batch delay,
            #however we must ensure this is not caused by a high system latency
            #so we ignore short elapsed times.
            elapsed = time.time()-self.last_damage_event_time
            mtime = max(0, elapsed-self.max_latency*2)
            #the longer the time, the more we slash:
            weight = sqrt(mtime)
            target = max(0, 1.0-mtime)
            metric = "damage-rate"
            info = {"elapsed"   : int(1000.0*elapsed),
                    "max_latency"   : int(1000.0*self.max_latency)}
            factors.append((metric, info, target, weight))
        return factors

    def add_stats(self, info, prefix, suffix=""):
        #encoding stats:
        if len(self.encoding_stats)>0:
            estats = list(self.encoding_stats)
            encodings_used = [x[0] for x in estats]
            def add_compression_stats(enc_stats, suffix):
                comp_ratios_pct = []
                comp_times_ns = []
                total_pixels = 0
                total_time = 0.0
                for _, pixels, compressed_size, compression_time in enc_stats:
                    if compressed_size>0 and pixels>0:
                        osize = pixels*3
                        comp_ratios_pct.append((100.0*compressed_size/osize, pixels))
                        comp_times_ns.append((1000.0*1000*1000*compression_time/pixels, pixels))
                        total_pixels += pixels
                        total_time += compression_time
                add_weighted_list_stats(info, prefix+"compression.ratio_pct"+suffix, comp_ratios_pct)
                add_weighted_list_stats(info, prefix+"compression.pixels_per_ns"+suffix, comp_times_ns)
                if total_time>0:
                    info[prefix+"encoding.pixels_encoded_per_second"+suffix] = int(total_pixels / total_time)
            add_compression_stats(estats, suffix=suffix)
            for encoding in encodings_used:
                enc_stats = [x for x in estats if x[0]==encoding]
                add_compression_stats(enc_stats, suffix="%s[%s]" % (suffix, encoding))

        latencies = [x*1000 for _, _, _, x in list(self.damage_in_latency)]
        add_list_stats(info, prefix+"damage.in_latency",  latencies, show_percentile=[9])
        latencies = [x*1000 for _, _, _, x in list(self.damage_out_latency)]
        add_list_stats(info, prefix+"damage.out_latency",  latencies, show_percentile=[9])
        #per encoding totals:
        for encoding, totals in self.encoding_totals.items():
            info[prefix+"total_frames%s[%s]" % (suffix, encoding)] = totals[0]
            info[prefix+"total_pixels%s[%s]" % (suffix, encoding)] = totals[1]
        info[prefix+"damage.events%s" % suffix] = self.damage_events_count
        info[prefix+"damage.packets_sent%s" % suffix] = self.packet_count

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

    def get_backlog(self):
        packets_backlog, pixels_backlog, bytes_backlog = 0, 0, 0
        if len(self.damage_ack_pending)>0:
            sent_before = time.time()-self.target_latency
            dropped_acks_time = time.time()-60      #1 minute
            drop_missing_acks = []
            for sequence, (start_send_at, start_bytes, end_send_at, end_bytes, pixels) in list(self.damage_ack_pending.items()):
                if end_send_at==0 or start_send_at>sent_before:
                    continue
                if start_send_at<dropped_acks_time:
                    drop_missing_acks.append(sequence)
                else:
                    packets_backlog += 1
                    pixels_backlog += pixels
                    bytes_backlog += (end_bytes - start_bytes)
            log.debug("get_backlog missing acks: %s", drop_missing_acks)
            #this should never happen...
            if len(drop_missing_acks)>0:
                log.error("get_backlog found some damage acks that have been pending for too long, expiring them: %s", drop_missing_acks)
                for sequence in drop_missing_acks:
                    try:
                        del self.damage_ack_pending[sequence]
                    except:
                        pass
        return packets_backlog, pixels_backlog, bytes_backlog

    def get_packets_backlog(self):
        packets_backlog = 0
        if len(self.damage_ack_pending)>0:
            sent_before = time.time()-self.target_latency
            for _, (start_send_at, _, end_send_at, _, _) in list(self.damage_ack_pending.items()):
                if end_send_at>0 and start_send_at<=sent_before:
                    packets_backlog += 1
        return packets_backlog
