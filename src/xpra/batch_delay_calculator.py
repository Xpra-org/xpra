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

from xpra.maths import dec1, dec2, logp, \
        calculate_time_weighted_average, calculate_timesize_weighted_average, \
        calculate_for_target, calculate_for_average, queue_inspect



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


AUTO_SPEED = env_bool("XPRA_AUTO_SPEED", True)
AUTO_QUALITY = env_bool("XPRA_AUTO_QUALITY", True)
MAX_NONVIDEO_PIXELS = 512
try:
    MAX_NONVIDEO_PIXELS = int(os.environ.get("XPRA_MAX_NONVIDEO_PIXELS", 2048))
except:
    pass

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



def calculate_batch_delay(window, wid, batch, global_statistics, statistics,
                          video_encoder=None, video_encoder_lock=None, video_encoder_speed=None, video_encoder_quality=None):
    """
        Calculates a new batch delay.
        We first gather some statistics,
        then use them to calculate a number of factors.
        which are then used to adjust the batch delay in 'update_batch_delay'.
    """
    #the number of pixels which can be considered 'low' in terms of backlog.
    #Generally, just one full frame, (more with mmap because it is so fast)
    low_limit = 1024*1024
    if window:
        ww, wh = window.get_dimensions()
        low_limit = max(8*8, ww*wh)
        if global_statistics.mmap_size>0:
            #mmap can accumulate much more as it is much faster
            low_limit *= 4
    #client latency: (how long it takes for a packet to get to the client and get the echo back)
    avg_client_latency, recent_client_latency = 0.1, 0.1    #assume 100ms until we get some data
    if len(global_statistics.client_latency)>0:
        data = [(when, latency) for _, when, _, latency in list(global_statistics.client_latency)]
        avg_client_latency, recent_client_latency = calculate_time_weighted_average(data)
    #damage "in" latency: (the time it takes for damage requests to be processed only)
    avg_damage_in_latency, recent_damage_in_latency = 0, 0
    if len(statistics.damage_in_latency)>0:
        data = [(when, latency) for when, _, _, latency in list(statistics.damage_in_latency)]
        avg_damage_in_latency, recent_damage_in_latency =  calculate_time_weighted_average(data)
    #damage "out" latency: (the time it takes for damage requests to be processed and sent out)
    avg_damage_out_latency, recent_damage_out_latency = 0, 0
    if len(statistics.damage_out_latency)>0:
        data = [(when, latency) for when, _, _, latency in list(statistics.damage_out_latency)]
        avg_damage_out_latency, recent_damage_out_latency = calculate_time_weighted_average(data)
    #client decode speed:
    avg_decode_speed, recent_decode_speed = None, None
    if len(statistics.client_decode_time)>0:
        #the elapsed time recorded is in microseconds, so multiply by 1000*1000 to get the real value:
        avg_decode_speed, recent_decode_speed = calculate_timesize_weighted_average(list(statistics.client_decode_time), sizeunit=1000*1000)
    #network send speed:
    avg_send_speed, recent_send_speed = None, None
    if len(statistics.damage_send_speed)>0:
        avg_send_speed, recent_send_speed = calculate_timesize_weighted_average(list(statistics.damage_send_speed))
    #client backlog: (packets and pixels that should have been processed by now - taking into account latency)
    packets_backlog, pixels_backlog = 0, 0
    if len(statistics.damage_ack_pending)>0:
        sent_before = time.time()-avg_client_latency
        for sent_at, pixels in statistics.damage_ack_pending.values():
            if sent_at>sent_before:
                continue
            packets_backlog += 1
            pixels_backlog += pixels
        statistics.last_client_delta = packets_backlog, pixels_backlog
    max_latency = max(avg_damage_in_latency, recent_damage_in_latency, avg_damage_out_latency, recent_damage_out_latency)

    #for each indicator: (description, factor, weight)
    factors = []

    #damage "in" latency factor:
    if len(statistics.damage_in_latency)>0:
        msg = "damage processing latency:"
        target_latency = 0.010 + (0.050*low_limit/1024.0/1024.0)
        factors.append(calculate_for_target(msg, target_latency, avg_damage_in_latency, recent_damage_in_latency, aim=0.8, slope=0.005, smoothing=sqrt))
    #damage "out" latency
    if len(statistics.damage_out_latency)>0:
        msg = "damage send latency:"
        target_latency = 0.025 + (0.060*low_limit/1024.0/1024.0)
        factors.append(calculate_for_target(msg, target_latency, avg_damage_out_latency, recent_damage_out_latency, aim=0.8, slope=0.010, smoothing=sqrt))
    #send speed:
    if avg_send_speed is not None and recent_send_speed is not None:
        #our calculate methods aims for lower values, so invert speed
        #this is how long it takes to send 1MB:
        avg1MB = 1.0*1024*1024/avg_send_speed
        recent1MB = 1.0*1024*1024/recent_send_speed
        #we only really care about this when the speed is quite low,
        #so adjust the weight accordingly:
        minspeed = float(128*1024)
        div = logp(max(recent_send_speed, minspeed)/minspeed)
        msg = "network send speed: avg=%s, recent=%s (KBytes/s), div=%s" % (int(avg_send_speed/1024), int(recent_send_speed/1024), div)
        factors.append(calculate_for_average(msg, avg1MB, recent1MB, weight_offset=1.0, weight_div=div))
    #client decode time:
    if avg_decode_speed is not None and recent_decode_speed is not None:
        msg = "client decode speed: avg=%s, recent=%s (MPixels/s)" % (dec1(avg_decode_speed/1000/1000), dec1(recent_decode_speed/1000/1000))
        #our calculate methods aims for lower values, so invert speed
        #this is how long it takes to send 1MB:
        avg1MB = 1.0*1024*1024/avg_decode_speed
        recent1MB = 1.0*1024*1024/recent_decode_speed
        factors.append(calculate_for_average(msg, avg1MB, recent1MB, weight_offset=0.0))
    #elapsed time without damage:
    if batch.last_updated>0:
        #If nothing happens for a while then we can reduce the batch delay,
        #however we must ensure this is not caused by a high damage latency
        #so we ignore short elapsed times.
        ignore_time = max(max_latency+batch.recalculate_delay, batch.delay+batch.recalculate_delay)
        ignore_count = 2 + ignore_time / batch.recalculate_delay
        elapsed = time.time()-batch.last_updated
        n_skipped_calcs = elapsed / batch.recalculate_delay
        #the longer the elapsed time, the more we slash:
        weight = logp(max(0, n_skipped_calcs-ignore_count))
        msg = "delay not updated for %s ms (skipped %s times - highest latency is %s)" % (dec1(1000*elapsed), int(n_skipped_calcs), dec1(1000*max_latency))
        factors.append((msg, 0, weight))
    #client latency: (we want to keep client latency as low as can be)
    if len(global_statistics.client_latency)>0 and avg_client_latency is not None and recent_client_latency is not None:
        target_latency = 0.005
        if global_statistics.min_client_latency:
            target_latency = max(target_latency, global_statistics.min_client_latency)
        msg = "client latency:"
        factors.append(calculate_for_target(msg, target_latency, avg_client_latency, recent_client_latency, aim=0.8, slope=0.005, smoothing=sqrt, weight_multiplier=4.0))
    #damage packet queue size: (includes packets from all windows)
    factors.append(queue_inspect("damage packet queue size:", global_statistics.damage_packet_qsizes, smoothing=sqrt))
    #damage pixels waiting in the packet queue: (extract data for our window id only)
    time_values = [(event_time, value) for event_time, dwid, value in list(global_statistics.damage_packet_qpixels) if dwid==wid]
    factors.append(queue_inspect("damage packet queue pixels:", time_values, div=low_limit, smoothing=sqrt))
    #damage data queue: (This is an important metric since each item will consume a fair amount of memory and each will later on go through the other queues.)
    factors.append(queue_inspect("damage data queue:", global_statistics.damage_data_qsizes))
    last_packets_backlog, last_pixels_backlog = 0, 0
    if statistics.last_client_delta is not None:
        #packet and pixels backlog:
        last_packets_backlog, last_pixels_backlog = statistics.last_client_delta
        factors.append(calculate_for_target("client packets backlog:", 0, last_packets_backlog, packets_backlog, slope=1.0, smoothing=sqrt))
        factors.append(calculate_for_target("client pixels backlog:", 0, last_pixels_backlog, pixels_backlog, div=low_limit, slope=1.0, smoothing=sqrt))
    if global_statistics.mmap_size>0:
        #full: effective range is 0.0 to ~1.2
        full = 1.0-float(global_statistics.mmap_free_size)/global_statistics.mmap_size
        #aim for ~50%
        factors.append(("mmap area %s%% full" % int(100*full), logp(2*full), 2*full))
    #now use those factors to drive the delay change:
    update_batch_delay(batch, factors)
    #***************************************************************
    #special hook for video encoders
    if (not AUTO_QUALITY and not AUTO_SPEED) or video_encoder is None:
        return

    #***********************************************************
    # encoding speed:
    #    0    for highest compression/slower
    #    100  for lowest compression/fast
    # here we try to minimize damage-latency and client decoding speed
    min_damage_latency = 0.010 + (0.050*low_limit/1024.0/1024.0)
    target_damage_latency = min_damage_latency + batch.delay/1000.0
    dam_lat = (avg_damage_in_latency or 0)/target_damage_latency
    target_decode_speed = 1*1000*1000      #1 MPixels/s
    dec_lat = target_decode_speed/(avg_decode_speed or target_decode_speed)
    target = max(dam_lat, dec_lat, 0.0)
    target_speed = 100.0 * min(1.0, target)
    video_encoder_speed.append((time.time(), target_speed))
    _, new_speed = calculate_time_weighted_average(video_encoder_speed)
    msg = "video encoder speed factors: min_damage_latency=%s, target_damage_latency=%s, batch.delay=%s, dam_lat=%s, dec_lat=%s, target=%s, new_speed=%s", \
             dec2(min_damage_latency), dec2(target_damage_latency), dec2(batch.delay), dec2(dam_lat), dec2(dec_lat), int(target_speed), int(new_speed)
    log(*msg)
    if DEBUG_DELAY:
        add_DEBUG_DELAY_MESSAGE(msg)
    #***********************************************************
    # quality:
    #    0    for lowest quality (low bandwidth usage)
    #    100  for best quality (high bandwidth usage)
    # here we try minimize client-latency, packet-backlog and batch.delay
    packets_bl = 1.0 - logp(last_packets_backlog/low_limit)
    batch_q = 4.0 * batch.min_delay / batch.delay
    target = max(packets_bl, batch_q)
    latency_q = 0.0
    if len(global_statistics.client_latency)>0 and avg_client_latency is not None and recent_client_latency is not None:
        target_latency = 0.005
        if global_statistics.min_client_latency:
            target_latency = max(target_latency, global_statistics.min_client_latency)
        latency_q = 4.0 * target_latency / recent_client_latency
        target = min(target, latency_q)
    target_quality = 100.0*(min(1.0, max(0.0, target)))
    video_encoder_quality.append((time.time(), target_quality))
    new_quality, _ = calculate_time_weighted_average(video_encoder_quality)
    msg = "video encoder quality factors: packets_bl=%s, batch_q=%s, latency_q=%s, target=%s, new_quality=%s", \
             dec2(packets_bl), dec2(batch_q), dec2(latency_q), int(target_quality), int(new_quality)
    log(*msg)
    if DEBUG_DELAY:
        add_DEBUG_DELAY_MESSAGE(msg)
    try:
        video_encoder_lock.acquire()
        if AUTO_SPEED:
            video_encoder.set_encoding_speed(new_speed)
        if AUTO_QUALITY:
            video_encoder.set_encoding_quality(new_quality)
    finally:
        video_encoder_lock.release()


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
    if len(batch.last_delays)>0:
        #get the weighted average
        #older values matter less, we decay them according to how much we batch already
        #(older values matter more when we batch a lot)
        for when, delay in batch.last_delays:
            #newer matter more:
            w = 1.0/(1.0+((now-when)/decay)**2)
            d = max(batch.min_delay, min(batch.max_delay, delay))
            tv += d*w
            tw += w
        avg = tv / tw
    hist_w = tw

    valid_factors = [x for x in factors if x is not None]
    all_factors_weight = sum([w for _,_,w in valid_factors])
    if all_factors_weight==0:
        log("update_batch_delay: no weights yet!")
        return
    max_factor = max([f for _,f,_ in valid_factors])
    #mitigate low factors if we have some really high ones:
    factor_min_limit = min(0.5, max_factor/10.0)
    for _, factor, weight in valid_factors:
        actual_factor = max(factor_min_limit, factor)
        target_delay = max(batch.min_delay, min(batch.max_delay, current_delay*actual_factor))
        w = max(1, hist_w)*weight/all_factors_weight
        tw += w
        tv += target_delay*w
    batch.delay = max(batch.min_delay, min(batch.max_delay, tv / tw))
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
