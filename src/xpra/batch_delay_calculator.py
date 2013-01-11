# coding=utf8
# This file is part of Parti.
# Copyright (C) 2012 Antoine Martin <antoine@devloop.org.uk>
# Parti is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import time
import os
import gobject

from math import sqrt

from wimpiggy.log import Logger
log = Logger()

from xpra.stats.base import dec1, dec2
from xpra.stats.maths import time_weighted_average, queue_inspect, logp


def env_bool(varname, defaultvalue=False):
    v = os.environ.get(varname)
    if v is None:
        return  defaultvalue
    v = v.lower()
    if v in ["1", "true", "on"]:
        return  True
    if v in ["0", "false", "off"]:
        return  False
    return  defaultvalue


MAX_DEBUG_MESSAGES = 1000
DEBUG_DELAY = env_bool("XPRA_DEBUG_LATENCY", False)

if DEBUG_DELAY:
    _debug_delay_messages = []

    def dump_debug_delay_messages():
        global _debug_delay_messages
        log.info("dump_debug_delay_messages():")
        for x in list(_debug_delay_messages):
            log.info(*x)
        _debug_delay_messages = []
        return  True

    def add_DEBUG_DELAY_MESSAGE(message):
        global _debug_delay_messages
        if len(_debug_delay_messages)>=MAX_DEBUG_MESSAGES:
            dump_debug_delay_messages()
        _debug_delay_messages.append(message)

    gobject.timeout_add(30*1000, dump_debug_delay_messages)
else:
    def add_DEBUG_DELAY_MESSAGE(message):
        pass


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
    factors = statistics.get_factors(low_limit)
    statistics.target_latency = statistics.get_target_client_latency(global_statistics.min_client_latency, global_statistics.avg_client_latency)
    factors += global_statistics.get_factors(statistics.target_latency, low_limit)
    #damage pixels waiting in the packet queue: (extract data for our window id only)
    time_values = global_statistics.get_damage_pixels(wid)
    factors.append(queue_inspect("damage packet queue window pixels:", time_values, div=low_limit, smoothing=sqrt))
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
    last_updated = batch.last_updated
    current_delay = batch.delay
    now = time.time()
    avg = 0
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
    if tw>0:
        avg = tv / tw
    hist_w = tw

    valid_factors = [x for x in factors if x is not None]
    all_factors_weight = sum([w for _,_,w in valid_factors])
    if all_factors_weight==0:
        log("update_batch_delay: no weights yet!")
        return
    for _, factor, weight in valid_factors:
        target_delay = max(0, min(max_delay, current_delay*factor))
        w = max(1, hist_w)*weight/all_factors_weight
        tw += w
        tv += target_delay*w
    batch.delay = max(0, min(max_delay, tv / tw))
    batch.last_updated = now
    if DEBUG_DELAY:
        decimal_delays = [dec1(x) for _,x in batch.last_delays]
        if len(decimal_delays)==0:
            decimal_delays.append(0)
        logfactors = [(msg, dec2(f), dec2(w)) for (msg, f, w) in valid_factors]
        rec = ("update_batch_delay: wid=%s, last updated %s ms ago, decay=%s, change factor=%s%%, delay min=%s, avg=%s, max=%s, cur=%s, w. average=%s, tot wgt=%s, hist_w=%s, new delay=%s\n %s",
                batch.wid, dec2(1000.0*now-1000.0*last_updated), dec2(decay), dec1(100*(batch.delay/current_delay-1)), min(decimal_delays), dec1(sum(decimal_delays)/len(decimal_delays)), max(decimal_delays),
                dec1(current_delay), dec1(avg), dec1(tw), dec1(hist_w), dec1(batch.delay), "\n ".join([str(x) for x in logfactors]))
        add_DEBUG_DELAY_MESSAGE(rec)


def update_video_encoder(window_dimensions, batch, global_statistics, statistics,
                          video_encoder=None, video_encoder_lock=None,
                          video_encoder_speed=None, video_encoder_quality=None,
                          fixed_quality=-1, fixed_speed=-1):
    low_limit = get_low_limit(global_statistics.mmap_size>0, window_dimensions)
    #***********************************************************
    # encoding speed:
    #    0    for highest compression/slower
    #    100  for lowest compression/fast
    # here we try to minimize damage-latency and client decoding speed
    if fixed_speed>=0:
        new_speed = fixed_speed
        msg = "video encoder using fixed speed: %s", fixed_speed
    else:
        #20ms + 50ms per MPixel
        min_damage_latency = 0.020 + 0.050*low_limit/1024.0/1024.0
        target_damage_latency = min_damage_latency + 10*batch.delay/1000.0
        dam_lat = max(0, ((statistics.avg_damage_in_latency or 0)-target_damage_latency)*5)
        target_decode_speed = 2*1000*1000      #2 MPixels/s
        dec_lat = 0.0
        if statistics.avg_decode_speed:
            dec_lat = target_decode_speed/(statistics.avg_decode_speed or target_decode_speed)
        target = max(dam_lat, dec_lat, 0.0)
        target_speed = 100.0 * min(1.0, target)
        #make a copy to work on
        ves_copy = list(video_encoder_speed)
        ves_copy.append((time.time(), target_speed))
        new_speed = time_weighted_average(ves_copy, rpow=1.2)
        video_encoder_speed.append((time.time(), new_speed))
        msg = "video encoder speed factors: low_limit=%s, min_damage_latency=%s, target_damage_latency=%s, batch.delay=%s, dam_lat=%s, dec_lat=%s, target=%s, new_speed=%s", \
                 low_limit, dec2(min_damage_latency), dec2(target_damage_latency), dec2(batch.delay), dec2(dam_lat), dec2(dec_lat), int(target_speed), int(new_speed)
    log(*msg)
    if DEBUG_DELAY:
        add_DEBUG_DELAY_MESSAGE(msg)
    #***********************************************************
    # quality:
    #    0    for lowest quality (low bandwidth usage)
    #    100  for best quality (high bandwidth usage)
    # here we try minimize client-latency, packet-backlog and batch.delay
    if fixed_quality>=0:
        new_quality = fixed_quality
        msg = "video encoder using fixed quality: %s", fixed_quality
    else:
        packets_backlog, _, _ = statistics.get_backlog()
        packets_bl = 1.0 - logp(packets_backlog/low_limit)
        batch_q = batch.min_delay / max(batch.min_delay, batch.delay)
        target = min(packets_bl, batch_q)
        latency_q = 0.0
        if len(global_statistics.client_latency)>0 and global_statistics.recent_client_latency>0:
            latency_q = 6.0 * statistics.target_latency / global_statistics.recent_client_latency
            target = min(target, latency_q)
        target_quality = 100.0*(min(1.0, max(0.0, target)))
        #make a copy to work on
        veq_copy = list(video_encoder_quality)
        veq_copy.append((time.time(), target_quality))
        new_quality = time_weighted_average(veq_copy, rpow=1.4)
        video_encoder_quality.append((time.time(), new_quality))
        msg = "video encoder quality factors: packets_bl=%s, batch_q=%s, latency_q=%s, target=%s, new_quality=%s", \
                 dec2(packets_bl), dec2(batch_q), dec2(latency_q), int(target_quality), int(new_quality)
    log(*msg)
    if DEBUG_DELAY:
        add_DEBUG_DELAY_MESSAGE(msg)
    try:
        video_encoder_lock.acquire()
        if not video_encoder.is_closed():
            video_encoder.set_encoding_speed(new_speed)
            video_encoder.set_encoding_quality(new_quality)
    finally:
        video_encoder_lock.release()
