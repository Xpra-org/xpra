# coding=utf8
# This file is part of Xpra.
# Copyright (C) 2011 Serviware (Arthur Huillet, <ahuillet@serviware.com>)
# Copyright (C) 2010-2013 Antoine Martin <antoine@devloop.org.uk>
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from math import sqrt
import time

from xpra.log import Logger
log = Logger()

from xpra.deque import maxdeque
from xpra.server.stats.maths import logp, calculate_time_weighted_average, calculate_for_target, queue_inspect
from xpra.simple_stats import add_list_stats

NRECS = 500
debug = log.debug


class GlobalPerformanceStatistics(object):
    """
    Statistics which are shared by all WindowSources
    """
    def __init__(self):
        self.reset()

    #assume 100ms until we get some data to compute the real values
    DEFAULT_LATENCY = 0.1

    def reset(self):
        # mmap state:
        self.mmap_size = 0
        self.mmap_bytes_sent = 0
        self.mmap_free_size = 0                         #how much of the mmap space is left (may be negative if we failed to write the last chunk)
        # queue statistics:
        self.damage_data_qsizes = maxdeque(NRECS)       #size of the damage_data_queue before we add a new record to it
                                                        #(event_time, size)
        self.damage_packet_qsizes = maxdeque(NRECS)     #size of the damage_packet_queue before we add a new packet to it
                                                        #(event_time, size)
        self.damage_packet_qpixels = maxdeque(NRECS)    #number of pixels waiting in the damage_packet_queue for a specific window,
                                                        #before we add a new packet to it
                                                        #(event_time, wid, size)
        self.damage_last_events = maxdeque(NRECS)       #records the x11 damage requests as they are received:
                                                        #(wid, event time, no of pixels)
        self.client_decode_time = maxdeque(NRECS)       #records how long it took the client to decode frames:
                                                        #(wid, event_time, no of pixels, decoding_time*1000*1000)
        self.client_latency = maxdeque(NRECS)           #how long it took for a packet to get to the client and get the echo back.
                                                        #(wid, event_time, no of pixels, client_latency)
        self.client_ping_latency = maxdeque(NRECS)      #time it took to get a ping_echo back from the client:
                                                        #(event_time, elapsed_time_in_seconds)
        self.server_ping_latency = maxdeque(NRECS)      #time it took for the client to get a ping_echo back from us:
                                                        #(event_time, elapsed_time_in_seconds)
        self.client_load = None
        self.damage_events_count = 0
        self.packet_count = 0
        #these values are calculated from the values above (see update_averages)
        self.min_client_latency = self.DEFAULT_LATENCY
        self.avg_client_latency = self.DEFAULT_LATENCY
        self.recent_client_latency = self.DEFAULT_LATENCY
        self.min_client_ping_latency = self.DEFAULT_LATENCY
        self.avg_client_ping_latency = self.DEFAULT_LATENCY
        self.recent_client_ping_latency = self.DEFAULT_LATENCY
        self.min_server_ping_latency = self.DEFAULT_LATENCY
        self.avg_server_ping_latency = self.DEFAULT_LATENCY
        self.recent_server_ping_latency = self.DEFAULT_LATENCY

    def record_latency(self, wid, decode_time, start_send_at, end_send_at, pixels, bytecount):
        now = time.time()
        send_diff = now-start_send_at
        echo_diff = now-end_send_at
        send_latency = max(0, send_diff-decode_time/1000.0/1000.0)
        echo_latency = max(0, echo_diff-decode_time/1000.0/1000.0)
        debug("record_latency: took %.1f ms round trip (%.1f just for echo), %.1f for decoding of %s pixels, %s bytes sent over the network in %.1f ms (%.1f ms for echo)",
                send_diff*1000, echo_diff*1000, decode_time/1000, pixels, bytecount, send_latency*1000, echo_latency*1000)
        if self.min_client_latency is None or self.min_client_latency>send_latency:
            self.min_client_latency = send_latency
        self.client_latency.append((wid, time.time(), pixels, send_latency))

    def get_damage_pixels(self, wid):
        """ returns the list of (event_time, pixelcount) for the given window id """
        return [(event_time, value) for event_time, dwid, value in list(self.damage_packet_qpixels) if dwid==wid]

    def update_averages(self):
        if len(self.client_latency)>0:
            data = [(when, latency) for _, when, _, latency in list(self.client_latency)]
            self.min_client_latency = min([x for _,x in data])
            self.avg_client_latency, self.recent_client_latency = calculate_time_weighted_average(data)
        #client ping latency: from ping packets
        if len(self.client_ping_latency)>0:
            data = list(self.client_ping_latency)
            self.min_client_ping_latency = min([x for _,x in data])
            self.avg_client_ping_latency, self.recent_client_ping_latency = calculate_time_weighted_average(data)
        #server ping latency: from ping packets
        if len(self.server_ping_latency)>0:
            data = list(self.server_ping_latency)
            self.min_server_ping_latency = min([x for _,x in data])
            self.avg_server_ping_latency, self.recent_server_ping_latency = calculate_time_weighted_average(data)

    def get_factors(self, target_latency, pixel_count):
        factors = []
        if len(self.client_latency)>0:
            #client latency: (we want to keep client latency as low as can be)
            metric = "client-latency"
            l = 0.005 + self.min_client_latency
            wm = logp(l / 0.020)
            factors.append(calculate_for_target(metric, l, self.avg_client_latency, self.recent_client_latency, aim=0.8, slope=0.005, smoothing=sqrt, weight_multiplier=wm))
        if len(self.client_ping_latency)>0:
            metric = "client-ping-latency"
            l = 0.005 + self.min_client_ping_latency
            wm = logp(l / 0.050)
            factors.append(calculate_for_target(metric, l, self.avg_client_ping_latency, self.recent_client_ping_latency, aim=0.95, slope=0.005, smoothing=sqrt, weight_multiplier=wm))
        if len(self.server_ping_latency)>0:
            metric = "server-ping-latency"
            l = 0.005 + self.min_server_ping_latency
            wm = logp(l / 0.050)
            factors.append(calculate_for_target(metric, l, self.avg_server_ping_latency, self.recent_server_ping_latency, aim=0.95, slope=0.005, smoothing=sqrt, weight_multiplier=wm))
        #damage packet queue size: (includes packets from all windows)
        factors.append(queue_inspect("damage-packet-queue-size", self.damage_packet_qsizes, smoothing=sqrt))
        #damage packet queue pixels (global):
        qpix_time_values = [(event_time, value) for event_time, _, value in list(self.damage_packet_qpixels)]
        factors.append(queue_inspect("damage-packet-queue-pixels", qpix_time_values, div=pixel_count, smoothing=sqrt))
        #damage data queue: (This is an important metric since each item will consume a fair amount of memory and each will later on go through the other queues.)
        factors.append(queue_inspect("damage-data-queue", self.damage_data_qsizes))
        if self.mmap_size>0:
            #full: effective range is 0.0 to ~1.2
            full = 1.0-float(self.mmap_free_size)/self.mmap_size
            #aim for ~33%
            factors.append(("mmap-area", "%s%% full" % int(100*full), logp(3*full), (3*full)**2))
        return factors

    def add_stats(self, info, suffix=""):
        info["damage_events%s" % suffix] = self.damage_events_count
        info["damage_packets_sent%s" % suffix] = self.packet_count
        info["output_mmap_bytecount%s" % suffix] = self.mmap_bytes_sent
        if self.min_client_latency is not None:
            info["client_latency%s.absmin" % suffix] = int(self.min_client_latency*1000)
        qsizes = [x for _,x in list(self.damage_data_qsizes)]
        add_list_stats(info, "damage_data_queue_size%s" % suffix,  qsizes)
        qsizes = [x for _,x in list(self.damage_packet_qsizes)]
        add_list_stats(info, "damage_packet_queue_size%s" % suffix,  qsizes)
        latencies = [x*1000 for (_, _, _, x) in list(self.client_latency)]
        add_list_stats(info, "client_latency%s" % suffix,  latencies)

        add_list_stats(info, "server_ping_latency%s" % suffix, [1000.0*x for _, x in list(self.server_ping_latency)])
        add_list_stats(info, "client_ping_latency%s" % suffix, [1000.0*x for _, x in list(self.client_ping_latency)])

        #client pixels per second:
        now = time.time()
        time_limit = now-30             #ignore old records (30s)
        #pixels per second: decode time and overall
        total_pixels = 0                #total number of pixels processed
        total_time = 0                  #total decoding time
        start_time = None               #when we start counting from (oldest record)
        region_sizes = []
        for _, event_time, pixels, decode_time in list(self.client_decode_time):
            #time filter and ignore failed decoding (decode_time==0)
            if event_time<time_limit or decode_time<=0:
                continue
            if start_time is None or start_time>event_time:
                start_time = event_time
            total_pixels += pixels
            total_time += decode_time
            region_sizes.append(pixels)
        debug("total_time=%s, total_pixels=%s", total_time, total_pixels)
        if total_time>0:
            pixels_decoded_per_second = int(total_pixels *1000*1000 / total_time)
            info["pixels_decoded_per_second%s" % suffix] = pixels_decoded_per_second
        if start_time:
            elapsed = now-start_time
            pixels_per_second = int(total_pixels/elapsed)
            info["pixels_per_second%s" % suffix] = pixels_per_second
            info["regions_per_second%s" % suffix] = int(len(region_sizes)/elapsed)
            info["average_region_size%s" % suffix] = int(total_pixels/len(region_sizes))
