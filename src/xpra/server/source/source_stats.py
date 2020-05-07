# -*- coding: utf-8 -*-
# This file is part of Xpra.
# Copyright (C) 2011 Serviware (Arthur Huillet, <ahuillet@serviware.com>)
# Copyright (C) 2010-2020 Antoine Martin <antoine@xpra.org>
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from math import sqrt
from collections import deque

from xpra.server.cystats import (                                           #@UnresolvedImport
    logp, calculate_time_weighted_average, calculate_size_weighted_average, #@UnresolvedImport
    calculate_for_target, time_weighted_average, queue_inspect,             #@UnresolvedImport
    )
from xpra.simple_stats import get_list_stats
from xpra.os_util import monotonic_time
from xpra.log import Logger

log = Logger("network")

NRECS = 500


class GlobalPerformanceStatistics:
    """
    Statistics which are shared by all WindowSources
    """
    def __init__(self):
        self.reset()

    #assume 100ms until we get some data to compute the real values
    DEFAULT_LATENCY = 0.1

    def reset(self, maxlen=NRECS):
        def d(maxlen=maxlen):
            return deque(maxlen=maxlen)
        # mmap state:
        self.mmap_size = 0
        self.mmap_bytes_sent = 0
        self.mmap_free_size = 0                             #how much of the mmap space is left (may be negative if we failed to write the last chunk)
        # queue statistics:
        self.compression_work_qsizes = d()                  #size of the compression_work_queue before we add a new record to it
                                                            #(event_time, size)
        self.packet_qsizes = d()                            #size of the packet_queue before we add a new packet to it
                                                            #(event_time, size)
        self.damage_packet_qpixels = d()                    #number of pixels waiting in the packet_queue for a specific window,
                                                            #before we add a new packet to it
                                                            #(event_time, wid, size)
        self.damage_last_events = d()                       #records the x11 damage requests as they are received:
                                                            #(wid, event time, no of pixels)
        self.client_decode_time = d()                       #records how long it took the client to decode frames:
                                                            #(wid, event_time, no of pixels, decoding_time*1000*1000)
        self.client_latency = d()                           #how long it took for a packet to get to the client and get the echo back.
                                                            #(wid, event_time, no of pixels, client_latency)
        self.client_ping_latency = d()                      #time it took to get a ping_echo back from the client:
                                                            #(event_time, elapsed_time_in_seconds)
        self.server_ping_latency = d()                      #time it took for the client to get a ping_echo back from us:
                                                            #(event_time, elapsed_time_in_seconds)
        self.congestion_send_speed = d(NRECS//4)            #when we are being throttled, record what speed we are sending at
                                                            #last NRECS: (event_time, lateness_pct, duration)
        self.bytes_sent = d(NRECS//4)                       #how much bandwidth we are using
                                                            #last NRECS: (sample_time, bytes)
        self.quality = d()                                  #quality used for sending updates:
                                                            #(event_time, no of pixels, quality)
        self.speed = d()                                    #speed used for sending updates:
                                                            #(event_time, no of pixels, speed)
        self.frame_total_latency = d()                      #how long it takes from the time we get a damage event
                                                            #until we get the ack back from the client
                                                            #(wid, event_time, no_of_pixels, latency)
        self.client_load = None
        self.last_congestion_time = 0
        self.congestion_value = 0
        self.damage_events_count = 0
        self.packet_count = 0
        self.decode_errors = 0
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
        self.avg_congestion_send_speed = 0
        self.avg_frame_total_latency = 0

    def record_latency(self, wid : int, decode_time, start_send_at, end_send_at, pixels, bytecount, latency):
        now = monotonic_time()
        send_diff = now-start_send_at
        echo_diff = now-end_send_at
        send_latency = max(0, send_diff-decode_time/1000.0/1000.0)
        echo_latency = max(0, echo_diff-decode_time/1000.0/1000.0)
        log("record_latency: took %6.1f ms round trip, %6.1f for echo, %6.1f for decoding of %8i pixels, %8i bytes sent over the network in %6.1f ms, %6.1f ms for echo",
                send_diff*1000, echo_diff*1000, decode_time/1000, pixels, bytecount, send_latency*1000, echo_latency*1000)
        if self.min_client_latency is None or self.min_client_latency>send_latency:
            self.min_client_latency = send_latency
        self.client_latency.append((wid, now, pixels, send_latency))
        self.frame_total_latency.append((wid, now, pixels, latency))

    def get_damage_pixels(self, wid):
        """ returns the list of (event_time, pixelcount) for the given window id """
        return [(event_time, value) for event_time, dwid, value in tuple(self.damage_packet_qpixels) if dwid==wid]

    def update_averages(self):
        def latency_averages(values):
            avg, recent = calculate_time_weighted_average(values)
            return max(0.001, avg), max(0.001, recent)
        client_latency = tuple(self.client_latency)
        if client_latency:
            data = tuple((when, latency) for _, when, _, latency in client_latency)
            self.min_client_latency = min(x for _,x in data)
            self.avg_client_latency, self.recent_client_latency = latency_averages(data)
        #client ping latency: from ping packets
        client_ping_latency = tuple(self.client_ping_latency)
        if client_ping_latency:
            self.min_client_ping_latency = min(x for _,x in client_ping_latency)
            self.avg_client_ping_latency, self.recent_client_ping_latency = latency_averages(client_ping_latency)
        #server ping latency: from ping packets
        server_ping_latency = tuple(self.server_ping_latency)
        if server_ping_latency:
            self.min_server_ping_latency = min(x for _,x in server_ping_latency)
            self.avg_server_ping_latency, self.recent_server_ping_latency = latency_averages(server_ping_latency)
        #set to 0 if we have less than 2 events in the last 60 seconds:
        now = monotonic_time()
        min_time = now-60
        css = tuple(x for x in tuple(self.congestion_send_speed) if x[0]>min_time)
        acss = 0
        if len(css)>=2:
            #weighted average of the send speed over the last minute:
            acss = int(calculate_size_weighted_average(css)[0])
            latest_ctime = self.congestion_send_speed[-1][0]
            elapsed = now-latest_ctime
            #require at least one recent event:
            if elapsed<30:
                #as the last event recedes in the past, increase limit:
                acss *= 1+elapsed
        self.avg_congestion_send_speed = int(acss)
        #how often we get congestion events:
        #first chunk it into second intervals
        min_time = now-10
        cst = tuple(x[0] for x in css)
        cps = []
        for t in range(10):
            etime = now-t
            matches = tuple(1 for x in cst if x>etime-1 and x<=etime) or (0,)
            cps.append((etime, sum(matches)))
        #log("cps(%s)=%s (now=%s)", cst, cps, now)
        self.congestion_value = time_weighted_average(cps)
        ftl = tuple(self.frame_total_latency)
        if ftl:
            edata = tuple((event_time, pixels, latency) for _, event_time, pixels, latency in ftl)
            #(wid, event_time, no_of_pixels, latency)
            self.avg_frame_total_latency = int(calculate_size_weighted_average(edata)[1])

    def get_factors(self, pixel_count):
        factors = []
        def mayaddfac(metric, info, factor, weight):
            if weight>0.01:
                factors.append((metric, info, factor, weight))
        if self.client_latency:
            #client latency: (we want to keep client latency as low as can be)
            metric = "client-latency"
            l = 0.005 + self.min_client_latency
            wm = logp(l / 0.020)
            mayaddfac(*calculate_for_target(metric, l, self.avg_client_latency, self.recent_client_latency,
                                            aim=0.8, slope=0.005, smoothing=sqrt, weight_multiplier=wm))
        if self.client_ping_latency:
            metric = "client-ping-latency"
            l = 0.005 + self.min_client_ping_latency
            wm = logp(l / 0.050)
            mayaddfac(*calculate_for_target(metric, l, self.avg_client_ping_latency, self.recent_client_ping_latency,
                                            aim=0.95, slope=0.005, smoothing=sqrt, weight_multiplier=wm))
        if self.server_ping_latency:
            metric = "server-ping-latency"
            l = 0.005 + self.min_server_ping_latency
            wm = logp(l / 0.050)
            mayaddfac(*calculate_for_target(metric, l, self.avg_server_ping_latency, self.recent_server_ping_latency,
                                            aim=0.95, slope=0.005, smoothing=sqrt, weight_multiplier=wm))
        #packet queue size: (includes packets from all windows)
        mayaddfac(*queue_inspect("packet-queue-size", self.packet_qsizes, smoothing=sqrt))
        #packet queue pixels (global):
        qpix_time_values = tuple((event_time, value) for event_time, _, value in tuple(self.damage_packet_qpixels))
        mayaddfac(*queue_inspect("packet-queue-pixels", qpix_time_values, div=pixel_count, smoothing=sqrt))
        #compression data queue: (This is an important metric
        #since each item will consume a fair amount of memory
        #and each will later on go through the other queues.)
        mayaddfac(*queue_inspect("compression-work-queue", self.compression_work_qsizes))
        if self.mmap_size>0:
            #full: effective range is 0.0 to ~1.2
            full = 1.0-self.mmap_free_size/self.mmap_size
            #aim for ~33%
            mayaddfac("mmap-area", "%s%% full" % int(100*full), logp(3*full), (3*full)**2)
        if self.congestion_value>0:
            mayaddfac("congestion", {}, 1+self.congestion_value, self.congestion_value*10)
        return factors

    def get_connection_info(self) -> dict:
        latencies = tuple(int(x*1000) for (_, _, _, x) in tuple(self.client_latency))
        info = {
            "mmap_bytecount"  : self.mmap_bytes_sent,
            "latency"           : get_list_stats(latencies),
            "server"            : {
                "ping_latency"   : get_list_stats(int(1000*x[1]) for x in tuple(self.server_ping_latency)),
                },
            "client"            : {
                "ping_latency"   : get_list_stats(int(1000*x[1]) for x in tuple(self.client_ping_latency)),
                },
            }
        if self.min_client_latency is not None:
            info["latency"] = {"absmin" : int(self.min_client_latency*1000)}
        return info


    def get_info(self) -> dict:
        cwqsizes = tuple(x[1] for x in tuple(self.compression_work_qsizes))
        pqsizes = tuple(x[1] for x in tuple(self.packet_qsizes))
        now = monotonic_time()
        time_limit = now-60             #ignore old records (60s)
        client_latency = max(0, self.avg_frame_total_latency-
                             int((self.avg_client_ping_latency+self.avg_server_ping_latency)//2))
        info = {
            "damage" : {
                "events"        : self.damage_events_count,
                "packets_sent"  : self.packet_count,
                "data_queue"    : {
                    "size"   : get_list_stats(cwqsizes),
                    },
                "packet_queue"  : {
                    "size"   : get_list_stats(pqsizes),
                    },
                "frame-total-latency" : self.avg_frame_total_latency,
                "client-latency"    : client_latency,
                },
            "encoding" : {"decode_errors"   : self.decode_errors},
            "congestion" : {
                "avg-send-speed"        : self.avg_congestion_send_speed,
                "elapsed-time"          : int(now-self.last_congestion_time),
                },
            "connection" : self.get_connection_info(),
            }
        if self.quality:
            ql = tuple(quality for _,_,quality in self.quality)
            info["encoding"]["quality"] = get_list_stats(ql)
        if self.speed:
            sl = tuple(speed for _,_,speed in self.speed)
            info["encoding"]["speed"] = get_list_stats(sl)
        #client pixels per second:
        #pixels per second: decode time and overall
        total_pixels = 0                #total number of pixels processed
        total_time = 0                  #total decoding time
        start_time = None               #when we start counting from (oldest record)
        region_sizes = []
        for _, event_time, pixels, decode_time in tuple(self.client_decode_time):
            #time filter and ignore failed decoding (decode_time==0)
            if event_time<time_limit or decode_time<=0:
                continue
            if start_time is None or start_time>event_time:
                start_time = event_time
            total_pixels += pixels
            total_time += decode_time
            region_sizes.append(pixels)
        log("total_time=%s, total_pixels=%s", total_time, total_pixels)
        if total_time>0:
            pixels_decoded_per_second = int(total_pixels *1000*1000 / total_time)
            info["encoding"]["pixels_decoded_per_second"] = pixels_decoded_per_second
        if start_time:
            elapsed = now-start_time
            pixels_per_second = int(total_pixels/elapsed)
            info.setdefault("encoding", {}).update({
                                                    "pixels_per_second"     : pixels_per_second,
                                                    "regions_per_second"    : int(len(region_sizes)/elapsed),
                                                    "average_region_size"   : int(total_pixels/len(region_sizes)),
                                                    })
        return info
