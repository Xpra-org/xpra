# coding=utf8
# This file is part of Xpra.
# Copyright (C) 2012, 2013 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import time
from math import sqrt

from xpra.log import Logger
log = Logger()

from xpra.server.stats.maths import queue_inspect, logp


def get_low_limit(mmap_enabled, window_dimensions):
    #the number of pixels which can be considered 'low' in terms of backlog.
    #Generally, just one full frame, (more with mmap because it is so fast)
    low_limit = 1024*1024
    ww, wh = window_dimensions
    if ww>0 and wh>0:
        low_limit = max(8*8, ww*wh)
    if mmap_enabled:
        #mmap can accumulate much more as it is much faster
        low_limit *= 4
    return low_limit


def calculate_batch_delay(window_dimensions, wid, batch, global_statistics, statistics):
    """
        Calculates a new batch delay.
        We first gather some statistics,
        then use them to calculate a number of factors.
        which are then used to adjust the batch delay in 'update_batch_delay'.
    """
    low_limit = get_low_limit(global_statistics.mmap_size>0, window_dimensions)

    #for each indicator: (description, factor, weight)
    factors = statistics.get_factors(low_limit, batch.delay)
    statistics.target_latency = statistics.get_target_client_latency(global_statistics.min_client_latency, global_statistics.avg_client_latency)
    factors += global_statistics.get_factors(statistics.target_latency, low_limit)
    #damage pixels waiting in the packet queue: (extract data for our window id only)
    time_values = global_statistics.get_damage_pixels(wid)
    factors.append(queue_inspect("damage-packet-queue-pixels", time_values, div=low_limit, smoothing=sqrt))
    #now use those factors to drive the delay change:
    update_batch_delay(batch, factors)


def update_batch_delay(batch, factors):
    """
        Given a list of factors of the form:
        [(description, factor, weight)]
        we calculate a new batch delay.
        We use a time-weighted average of previous delays as a starting value,
        then combine it with the new factors.
    """
    current_delay = batch.delay
    now = time.time()
    tv, tw = 0.0, 0.0
    decay = max(1, logp(current_delay/batch.min_delay)/5.0)
    max_delay = batch.max_delay
    for delays in (batch.last_delays, batch.last_actual_delays):
        if len(delays)>0:
            #get the weighted average
            #older values matter less, we decay them according to how much we batch already
            #(older values matter more when we batch a lot)
            for when, delay in list(delays):
                #newer matter more:
                w = 1.0/(1.0+((now-when)/decay)**2)
                d = max(0, min(max_delay, delay))
                tv += d*w
                tw += w
    hist_w = tw

    for x in factors:
        if len(x)!=4:
            log.warn("invalid factor line: %s" % str(x))
    valid_factors = [x for x in factors if x is not None and len(x)==4]
    all_factors_weight = sum([w for _,_,_,w in valid_factors])
    if all_factors_weight==0:
        log("update_batch_delay: no weights yet!")
        return
    for _, _, factor, weight in valid_factors:
        target_delay = max(0, min(max_delay, current_delay*factor))
        w = max(1, hist_w)*weight/all_factors_weight
        tw += w
        tv += target_delay*w
    batch.delay = max(0, min(max_delay, tv / tw))
    batch.last_updated = now
    batch.factors = valid_factors


def get_target_speed(wid, window_dimensions, batch, global_statistics, statistics, min_speed):
    low_limit = get_low_limit(global_statistics.mmap_size>0, window_dimensions)
    #***********************************************************
    # encoding speed:
    #    0    for highest compression/slower
    #    100  for lowest compression/fast
    # here we try to minimize damage-latency and client decoding speed
    #20ms + 50ms per MPixel
    min_damage_latency = 0.010 + 0.025*low_limit/1024.0/1024.0
    target_damage_latency = min_damage_latency + batch.delay/1000.0
    dam_lat_abs = max(0, ((statistics.avg_damage_in_latency or 0)-min_damage_latency)*10.0)
    dam_lat_rel = max(0, ((statistics.avg_damage_in_latency or 0)/target_damage_latency)/2.0)
    target_decode_speed = 8*1000*1000      #8 MPixels/s
    dec_lat = 0.0
    if statistics.avg_decode_speed:
        dec_lat = target_decode_speed/(statistics.avg_decode_speed or target_decode_speed)
    target = min(1.0, max(dam_lat_abs, dam_lat_rel, dec_lat, 0.0))
    ms = min(100.0, max(min_speed, 0.0))
    target_speed = ms + (100.0-ms) * target
    info = {
            "low_limit" : int(low_limit),
            "min_speed" : int(min_speed),
            "min_damage_latency"    : int(1000.0*min_damage_latency),
            "avg_damage_latency"    : int(1000.0*statistics.avg_damage_in_latency),
            "target_damage_latency" : int(1000.0*target_damage_latency),
            "batch.delay"   : int(batch.delay),
            "abs_factor"    : int(100.0*dam_lat_abs), 
            "rel_factor"    : int(100.0*dam_lat_rel),
            "decoding_latency_factor"   : int(100.0*dec_lat)
            }
    return info, target_speed


def get_target_quality(wid, window_dimensions, batch, global_statistics, statistics, min_quality):
    low_limit = get_low_limit(global_statistics.mmap_size>0, window_dimensions)
    #***********************************************************
    # quality:
    #    0    for lowest quality (low bandwidth usage)
    #    100  for best quality (high bandwidth usage)
    # here we try minimize client-latency, packet-backlog and batch.delay
    packets_backlog, _, _ = statistics.get_backlog()
    packets_bl = 1.0 - logp(packets_backlog/low_limit)
    target = packets_bl
    batch_q = -1
    recs = len(batch.last_actual_delays)
    if recs>0:
        #weighted average between start delay and min_delay
        #so when we start and we don't have any records, we don't lower quality
        #just because the start delay is higher than min_delay
        ref_delay = (batch.START_DELAY*10.0/recs + batch.min_delay*recs) / (recs+10.0/recs)
        batch_q = ref_delay / max(batch.min_delay, batch.delay)
        target = min(1.0, target, batch_q)
    latency_q = -1
    if len(global_statistics.client_latency)>0 and global_statistics.recent_client_latency>0:
        latency_q = 3.0 * statistics.target_latency / global_statistics.recent_client_latency
        target = min(target, latency_q)
    target = min(1.0, max(0.0, target))
    mq = min(100.0, max(min_quality, 0.0))
    target_quality = mq + (100.0-mq) * target
    info = {
            "min_quality"   : min_quality,
            "backlog_factor": int(100.0*packets_bl),
            "batch_factor"  : int(100.0*batch_q),
            "latency_factor": int(100.0*latency_q),
            } 
    return info, target_quality
