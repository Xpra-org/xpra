# -*- coding: utf-8 -*-
# This file is part of Xpra.
# Copyright (C) 2012-2019 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from math import log as mathlog, sqrt

from xpra.os_util import monotonic_time
from xpra.server.cystats import (   #@UnresolvedImport
    queue_inspect, logp, time_weighted_average,
    calculate_timesize_weighted_average_score,
    )
from xpra.log import Logger

log = Logger("server", "stats")


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


def calculate_batch_delay(wid, window_dimensions,
                          has_focus, other_is_fullscreen, other_is_maximized, is_OR,
                          soft_expired, batch, global_statistics, statistics, bandwidth_limit):
    """
        Calculates a new batch delay.
        We first gather some statistics,
        then use them to calculate a number of factors.
        which are then used to adjust the batch delay in 'update_batch_delay'.
    """
    low_limit = get_low_limit(global_statistics.mmap_size>0, window_dimensions)

    #for each indicator: (description, factor, weight)
    factors = statistics.get_factors(bandwidth_limit)
    statistics.target_latency = statistics.get_target_client_latency(global_statistics.min_client_latency,
                                                                     global_statistics.avg_client_latency)
    factors += global_statistics.get_factors(low_limit)
    #damage pixels waiting in the packet queue: (extract data for our window id only)
    time_values = global_statistics.get_damage_pixels(wid)
    def mayaddfac(metric, info, factor, weight):
        if weight>0.01:
            factors.append((metric, info, factor, weight))
    mayaddfac(*queue_inspect("damage-packet-queue-pixels", time_values, div=low_limit, smoothing=sqrt))
    #boost window that has focus and OR windows:
    mayaddfac("focus", {"has_focus" : has_focus}, int(not has_focus), int(has_focus))
    mayaddfac("override-redirect", {"is_OR" : is_OR}, int(not is_OR), int(is_OR))
    #soft expired regions is a strong indicator of problems:
    #(0 for none, up to max_soft_expired which is 5)
    mayaddfac("soft-expired", {"count" : soft_expired}, soft_expired, int(bool(soft_expired)))
    #now use those factors to drive the delay change:
    min_delay = 0
    if batch.always:
        min_delay = batch.min_delay
    #if another window is fullscreen or maximized,
    #make sure we don't use a very low delay (cap at 25fps)
    if other_is_fullscreen or other_is_maximized:
        min_delay = max(40, min_delay)
    update_batch_delay(batch, factors, min_delay)


def update_batch_delay(batch, factors, min_delay=0):
    """
        Given a list of factors of the form:
        [(description, factor, weight)]
        we calculate a new batch delay.
        We use a time-weighted average of previous delays as a starting value,
        then combine it with the new factors.
    """
    current_delay = batch.delay
    now = monotonic_time()
    tv, tw = 0.0, 0.0
    decay = max(1, logp(current_delay/batch.min_delay)/5.0)
    max_delay = batch.max_delay
    for delays, d_weight in ((batch.last_delays, 0.25), (batch.last_actual_delays, 0.75)):
        delays = tuple(delays or ())
        #get the weighted average
        #older values matter less, we decay them according to how much we batch already
        #(older values matter more when we batch a lot)
        for when, delay in delays:
            #newer matter more:
            w = d_weight/(1.0+((now-when)/decay)**2)
            d = max(0, min(max_delay, delay))
            tv += d*w
            tw += w
    hist_w = tw
    for x in factors:
        if len(x)!=4:
            log.warn("invalid factor line: %s" % str(x))
        else:
            log("update_batch_delay: %-28s : %.2f,%.2f  %s", x[0], x[2], x[3], x[1])
    valid_factors = tuple(x for x in factors if x is not None and len(x)==4)
    all_factors_weight = sum(vf[-1] for vf in valid_factors)
    if all_factors_weight==0:
        log("update_batch_delay: no weights yet!")
        return
    for _, _, factor, weight in valid_factors:
        target_delay = max(0, min(max_delay, current_delay*factor))
        w = max(1, hist_w)*weight/all_factors_weight
        tw += w
        tv += target_delay*w
    batch.delay = int(max(min_delay, min(max_delay, tv // tw)))
    try:
        last_actual_delay = batch.last_actual_delays[-1][-1]
    except IndexError:
        last_actual_delay = -1
    log("update_batch_delay: delay=%i (last actual delay: %s)", batch.delay, last_actual_delay)
    batch.last_updated = now
    batch.factors = valid_factors

def get_target_speed(window_dimensions, batch, global_statistics, statistics, bandwidth_limit, min_speed, speed_data):
    low_limit = get_low_limit(global_statistics.mmap_size>0, window_dimensions)
    #***********************************************************
    # encoding speed:
    #    0    for highest compression/slower
    #    100  for lowest compression/fast
    # here we try to minimize damage-latency and client decoding speed

    #backlog factor:
    _, pixels_backlog, _ = statistics.get_client_backlog()
    pb_ratio = pixels_backlog/low_limit
    pixels_bl_s = 100 - int(100*logp(pb_ratio/4))    #4 frames behind or more -> compress more

    #megapixels per second:
    mpixels = low_limit/1024.0/1024.0
    #for larger window sizes, we should be downscaling,
    #and don't want to wait too long for those anyway:
    ref_damage_latency = (10 + 25 * (1+mathlog(max(1, mpixels))))/1000.0

    adil = statistics.avg_damage_in_latency or 0
    #abs: try to never go higher than N times the reference latency:
    dam_lat_abs = max(0, (adil-ref_damage_latency)) / (ref_damage_latency * 3)

    if batch.locked:
        target_damage_latency = ref_damage_latency
        dam_lat_rel = 0
        frame_delay = 0
        dam_lat_s = 100
    else:
        #calculate a target latency and try to get close to it
        avg_delay = batch.delay
        delays = tuple(batch.last_actual_delays)
        if delays:
            #average recent actual delay:
            avg_delay = time_weighted_average(delays)
        #and average that with the current delay (which is lower or equal):
        frame_delay = max(10, int((avg_delay + batch.delay) // 2))
        #ensure we always spend at least as much time encoding as we spend batching:
        #(one frame encoding whilst one frame is batching is our ideal result)
        target_damage_latency = max(ref_damage_latency, frame_delay/1000.0)
        dam_target_speed = min_speed
        if speed_data:
            dam_target_speed = max(min_speed, time_weighted_average(speed_data))
        #rel: do we need to increase speed to reach the target:
        dam_lat_rel = dam_target_speed/100.0 * adil / target_damage_latency
        #cap the speed if we're delaying frames longer than we should:
        #(so we spend more of that time compressing them better instead):
        dam_lat_s = int(100*2*ref_damage_latency*1000//frame_delay)

    #if we have more pixels to encode, we may need to go faster
    #(this is important because the damage latency used by the other factors
    # may aggregate multiple damage requests into one packet - which may skip frames)
    #TODO: reconcile this with video regions
    #only count the last second's worth:
    now = monotonic_time()
    lim = now-1.0
    lde = tuple(w*h for t,_,_,w,h in tuple(statistics.last_damage_events) if t>=lim)
    pixels = sum(lde)
    mpixels_per_s = pixels/(1024*1024)
    pps = 0.0
    pixel_rate_s = 100
    if len(lde)>5 and mpixels_per_s>=1:
        #above 50 MPixels/s, we should reach 100% speed
        #(even x264 peaks at tens of MPixels/s)
        pps = sqrt(mpixels_per_s/50.0)
        #if there aren't many pixels,
        #we can spend more time compressing them better:
        #(since it isn't going to cost too much to compress)
        #ie: 2MPixels/s -> max_speed=60%
        pixel_rate_s = 20+int(mpixels_per_s*20)

    bandwidth_s = 100
    if bandwidth_limit>0:
        #below N Mbps, lower the speed ceiling,
        #so we will compress better:
        N = 10
        bandwidth_s = int(100*sqrt(bandwidth_limit/(N*1000*1000)))

    gcv = global_statistics.congestion_value
    congestion_s = 100
    if gcv>0:
        #apply strict limit for congestion events:
        congestion_s = max(0, int(100-gcv*1000))

    #ensure we decode at a reasonable speed (for slow / low-power clients)
    #maybe this should be configurable?
    min_decode_speed = 1*1000*1000      #MPixels/s
    ads = statistics.avg_decode_speed or 0
    dec_lat = 0
    if ads>0:
        dec_lat = min_decode_speed/ads

    ms = min(100, max(min_speed, 0))
    max_speed = max(ms, min(pixels_bl_s, dam_lat_s, pixel_rate_s, bandwidth_s, congestion_s))
    #combine factors: use the highest one:
    target = min(1, max(dam_lat_abs, dam_lat_rel, dec_lat, pps, 0))
    #scale target between min_speed and 100:
    speed = int(ms + (100-ms) * target)
    speed = max(ms, min(max_speed, speed))

    #expose data we used:
    info = {
            "low-limit"                 : int(low_limit),
            "max-speed"                 : int(max_speed),
            "min-speed"                 : int(min_speed),
            "factors"                   : {
                "damage-latency-abs"    : int(dam_lat_abs*100),
                "damage-latency-rel"    : int(dam_lat_rel*100),
                "decoding-latency"      : int(dec_lat*100),
                "pixel-rate"            : int(pps*100),
                },
            "limits"                    : {
                "backlog"               : pixels_bl_s,
                "damage-latency"        : dam_lat_s,
                "pixel-rate"            : pixel_rate_s,
                "bandwidth-limit"       : bandwidth_s,
                "congestion"            : congestion_s,
                },
            }
    return info, int(speed), max_speed


def get_target_quality(window_dimensions, batch,
                       global_statistics, statistics, bandwidth_limit,
                       min_quality, min_speed):
    low_limit = get_low_limit(global_statistics.mmap_size>0, window_dimensions)
    #***********************************************************
    # quality:
    #    0    for lowest quality (low bandwidth usage)
    #    100  for best quality (high bandwidth usage)
    # here we try minimize client-latency, packet-backlog and batch.delay
    # the compression ratio tells us if we can increase the quality

    #backlog factor:
    packets_backlog, pixels_backlog, _ = statistics.get_client_backlog()
    pb_ratio = pixels_backlog/low_limit
    pixels_bl_q = 1 - logp(pb_ratio/4)    #4 frames behind or more -> min quality

    #bandwidth limit factor:
    bandwidth_q = 1
    if bandwidth_limit>0:
        #below 10Mbps, lower the quality
        bandwidth_q = int(100*sqrt(bandwidth_limit/(10.0*1000*1000)))

    #congestion factor:
    gcv = global_statistics.congestion_value
    congestion_q = 1 - gcv*10

    #batch delay factor:
    batch_q = 1
    if batch is not None:
        recs = len(batch.last_actual_delays)
        if recs>0 and not batch.locked:
            #weighted average between start delay and min_delay
            #so when we start and we don't have any records, we don't lower quality
            #just because the start delay is higher than min_delay
            #anything less than N times the reference delay is good enough:
            N = 3.0-min_speed/50.0
            #if the min-speed is high, reduce tolerance:
            tolerance = 10-int(min_speed//10)
            ref_delay = max(0, tolerance+N*(batch.START_DELAY*10 + batch.min_delay*recs) // (recs+10))
            batch_q = (N * ref_delay) / max(1, batch.min_delay, batch.delay)

    #latency limit factor:
    latency_q = 1
    if global_statistics.client_latency and global_statistics.recent_client_latency>0:
        #if the recent latency is too high, keep quality lower:
        latency_q = 3.0 * statistics.target_latency / global_statistics.recent_client_latency

    #target is the lowest value of all those limits:
    target = max(0, min(1, pixels_bl_q, bandwidth_q, congestion_q, batch_q, latency_q))

    info = {}
    #boost based on recent compression ratio
    comp_boost = 0
    #from here on, the compression ratio integer value is in per-1000:
    es = tuple((t, pixels, 1000*compressed_size*bpp//pixels//32)
               for (t, _, pixels, bpp, compressed_size, _) in tuple(statistics.encoding_stats) if pixels>=4096)
    if len(es)>=2:
        #use the recent vs average compression ratio
        #(add value to smooth things out a bit, so very low compression ratios don't skew things)
        comp_boost = 0
        ascore, rscore = calculate_timesize_weighted_average_score(es)
        if ascore>rscore:
            #raise the quality
            #but only if there is no backlog:
            if packets_backlog==0:
                smooth = 150
                comp_boost = logp(((smooth+ascore)/(smooth+rscore)))-1.0
        else:
            #lower the quality
            #more so if the compression is not doing very well:
            mult = (1000 + rscore)/2000.0           #mult should be in the range 0.5 to ~1.0
            smooth = 50
            comp_boost = -logp(((smooth+rscore)/(smooth+ascore))-1.0) * mult
        info["compression-ratio"] = ascore, rscore
        target = max(0, target+comp_boost)

    #discount the quality more aggressively if we have speed requirements to satisfy:
    if min_speed>0:
        #ie: for min_speed=50:
        #target=1.0   -> target=1.0
        #target=0.8   -> target=0.51
        #target=0.5   -> target=0.125
        #target=0     -> target=0
        target = target ** ((100.0 + 4*min_speed)/100.0)

    #raise the quality when there are not many recent damage events:
    ww, wh = window_dimensions
    if ww>0 and wh>0:
        lde = tuple(statistics.last_damage_events)
        if lde:
            now = monotonic_time()
            damage_pixel_count = tuple((lim, sum(w*h for t,_,_,w,h in lde if now-lim<=t<now-lim+1))
                                       for lim in range(1,11))
            pixl5 = sum(v for lim,v in damage_pixel_count if lim<=5)
            pixn5 = sum(v for lim,v in damage_pixel_count if lim>5)
            pctpixdamaged = pixl5/(ww*wh)
            log("get_target_quality: target=%3i%% (window %4ix%-4i) pctpixdamaged=%3i%%, dpc=%s",
                100*target, ww, wh, pctpixdamaged*100, damage_pixel_count)
            if pctpixdamaged<0.5:
                target *= (1.5-pctpixdamaged)
            if pixl5<pixn5:
                target = sqrt(target)

    #apply min-quality:
    mq = min(100, max(min_quality, 0))
    quality = int(mq + (100-mq) * target)
    quality = max(0, mq, min(100, quality))

    info.update({
        "min-quality"       : min_quality,
        "min-speed"         : min_speed,
        "backlog"           : (packets_backlog, pixels_backlog, low_limit, int(100*pb_ratio)),
        "limits"           : {
            "backlog"       : int(pixels_bl_q*100),
            "bandwidth"     : int(bandwidth_q*100),
            "congestion"    : int(congestion_q*100),
            "batch"         : int(batch_q*100),
            "latency"       : int(latency_q*100),
            "boost"         : int(comp_boost*100),
            },
        })
    return info, int(quality)
