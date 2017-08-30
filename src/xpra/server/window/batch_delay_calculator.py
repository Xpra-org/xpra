# coding=utf8
# This file is part of Xpra.
# Copyright (C) 2012-2017 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from math import log as mathlog, sqrt

from xpra.log import Logger
log = Logger("server", "stats")

from xpra.os_util import monotonic_time
from xpra.server.cystats import queue_inspect, logp, time_weighted_average, calculate_timesize_weighted_average_score   #@UnresolvedImport


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


def calculate_batch_delay(wid, window_dimensions, has_focus, other_is_fullscreen, other_is_maximized, is_OR, soft_expired, batch, global_statistics, statistics):
    """
        Calculates a new batch delay.
        We first gather some statistics,
        then use them to calculate a number of factors.
        which are then used to adjust the batch delay in 'update_batch_delay'.
    """
    low_limit = get_low_limit(global_statistics.mmap_size>0, window_dimensions)

    #for each indicator: (description, factor, weight)
    factors = statistics.get_factors()
    statistics.target_latency = statistics.get_target_client_latency(global_statistics.min_client_latency, global_statistics.avg_client_latency)
    factors += global_statistics.get_factors(low_limit)
    #damage pixels waiting in the packet queue: (extract data for our window id only)
    time_values = global_statistics.get_damage_pixels(wid)
    factors.append(queue_inspect("damage-packet-queue-pixels", time_values, div=low_limit, smoothing=sqrt))
    #boost window that has focus and OR windows:
    factors.append(("focus", {"has_focus" : has_focus}, int(not has_focus), int(has_focus)))
    factors.append(("override-redirect", {"is_OR" : is_OR}, int(not is_OR), int(is_OR)))
    #if another window is fullscreen or maximized, slow us down:
    factors.append(("fullscreen", {"other_is_fullscreen" : other_is_fullscreen}, 4*int(other_is_fullscreen), int(other_is_fullscreen)))
    factors.append(("maximized", {"other_is_maximized" : other_is_maximized}, 4*int(other_is_maximized), int(other_is_maximized)))
    #soft expired regions is a strong indicator of problems:
    #(0 for none, up to max_soft_expired which is 5)
    factors.append(("soft-expired", {"count" : soft_expired}, soft_expired, int(bool(soft_expired))))
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
    now = monotonic_time()
    tv, tw = 0.0, 0.0
    decay = max(1, logp(current_delay/batch.min_delay)/5.0)
    max_delay = batch.max_delay
    for delays, d_weight in ((batch.last_delays, 0.25), (batch.last_actual_delays, 0.75)):
        if delays is not None and len(delays)>0:
            #get the weighted average
            #older values matter less, we decay them according to how much we batch already
            #(older values matter more when we batch a lot)
            for when, delay in list(delays):
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
    mv = 0
    if batch.always:
        mv = batch.min_delay
    batch.delay = max(mv, min(max_delay, tv // tw))
    log("update_batch_delay: delay=%i", batch.delay)
    batch.last_updated = now
    batch.factors = valid_factors

def get_target_speed(window_dimensions, batch, global_statistics, statistics, min_speed, speed_data):
    low_limit = get_low_limit(global_statistics.mmap_size>0, window_dimensions)
    #***********************************************************
    # encoding speed:
    #    0    for highest compression/slower
    #    100  for lowest compression/fast
    # here we try to minimize damage-latency and client decoding speed

    #megapixels per second:
    mpixels = low_limit/1024.0/1024.0
    #for larger window sizes, we should be downscaling,
    #and don't want to wait too long for those anyway:
    ref_damage_latency = 0.010 + 0.025 * (1+mathlog(max(1, mpixels)))

    #abs: try to never go higher than 5 times reference latency:
    dam_lat_abs = max(0, ((statistics.avg_damage_in_latency or 0)-ref_damage_latency) / (ref_damage_latency * 4.0))

    if batch.locked:
        target_damage_latency = ref_damage_latency
        dam_lat_rel = 0
        frame_delay = 0
    else:
        #calculate a target latency and try to get close to it
        avg_delay = batch.delay
        delays = list(batch.last_actual_delays)
        if len(delays)>0:
            #average recent actual delay:
            avg_delay = time_weighted_average(delays)
        #and average that with the current delay (which is lower or equal):
        frame_delay = (avg_delay + batch.delay) / 2.0
        #ensure we always spend at least as much time encoding as we spend batching:
        #(one frame encoding whilst one frame is batching is our ideal result)
        target_damage_latency = max(ref_damage_latency, frame_delay/1000.0)
        #current speed:
        speed = min_speed
        if len(speed_data)>0:
            speed = max(min_speed, time_weighted_average(speed_data))
        #rel: do we need to increase or decrease speed to reach the target:
        dam_lat_rel = speed/100.0 * statistics.avg_damage_in_latency / target_damage_latency

    #ensure we decode at a reasonable speed (for slow / low-power clients)
    #maybe this should be configurable?
    target_decode_speed = 8*1000*1000.0      #8 MPixels/s
    dec_lat = 0.0
    if statistics.avg_decode_speed>0:
        dec_lat = target_decode_speed/(statistics.avg_decode_speed or target_decode_speed)

    #if we have more pixels to encode, we may need to go faster
    #(this is important because the damage latency used by the other factors
    # may aggregate multiple damage requests into one packet - which may skip frames)
    #TODO: reconcile this with video regions
    #only count the last second's worth:
    now = monotonic_time()
    lim = now-1.0
    lde = [w*h for t,_,_,w,h in list(statistics.last_damage_events) if t>=lim]
    pixels = sum(lde)
    mpixels_per_s = pixels/1024.0/1024.0
    pps = 0.0
    if len(lde)>5:
        #above 50 MPixels/s, we should reach 100% speed
        #(even x264 peaks at tens of MPixels/s)
        pps = mpixels_per_s/50.0

    #combine factors: use the highest one:
    target = min(1.0, max(dam_lat_abs, dam_lat_rel, dec_lat, pps, 0.0))

    #scale target between min_speed and 100:
    ms = min(100.0, max(min_speed, 0.0))
    target_speed = int(ms + (100.0-ms) * target)

    #expose data we used:
    info = {
            "low_limit"                 : int(low_limit),
            "min_speed"                 : int(min_speed),
            "frame_delay"               : int(frame_delay),
            "mpixels"                   : int(mpixels_per_s),
            "damage_latency"            : {
                                           "ref"        : int(1000.0*ref_damage_latency),
                                           "avg"        : int(1000.0*statistics.avg_damage_in_latency),
                                           "target"     : int(1000.0*target_damage_latency),
                                           "abs_factor" : int(100.0*dam_lat_abs),
                                           "rel_factor" : int(100.0*dam_lat_rel),
                                           },
            "decoding_latency"          : {
                                           "target"   : int(target_decode_speed),
                                           "factor"   : int(100.0*dec_lat),
                                           },
            }
    return info, target_speed


def get_target_quality(window_dimensions, batch, global_statistics, statistics, min_quality, min_speed):
    info = {
        "min_quality"   : min_quality,
        "min_speed"     : min_speed,
        }
    low_limit = get_low_limit(global_statistics.mmap_size>0, window_dimensions)
    #***********************************************************
    # quality:
    #    0    for lowest quality (low bandwidth usage)
    #    100  for best quality (high bandwidth usage)
    # here we try minimize client-latency, packet-backlog and batch.delay
    # the compression ratio tells us if we can increase the quality
    packets_backlog, pixels_backlog, _ = statistics.get_client_backlog()
    pb_ratio = pixels_backlog/low_limit
    pixels_bl = 1.0 - logp(pb_ratio//4)     #4 frames behind -> min quality
    info["backlog_factor"] = packets_backlog, pixels_backlog, low_limit, pb_ratio, int(100.0*pixels_bl)
    target = pixels_bl
    if batch is not None:
        recs = len(batch.last_actual_delays)
        if recs>0 and not batch.locked:
            #weighted average between start delay and min_delay
            #so when we start and we don't have any records, we don't lower quality
            #just because the start delay is higher than min_delay
            ref_delay = (batch.START_DELAY*10.0/recs + batch.min_delay*recs) / (recs+10.0/recs)
            #anything less than N times the reference delay is good enough:
            N = 4
            batch_q = N * ref_delay / max(1, batch.min_delay, batch.delay)
            info["batch-delay-ratio"] = int(100.0*batch_q)
            target = min(1.0, target, batch_q)
    #from here on, the compression ratio integer value is in per-1000:
    es = [(t, pixels, 1000*compressed_size*bpp//pixels//32) for (t, _, pixels, bpp, compressed_size, _) in list(statistics.encoding_stats) if pixels>=4096]
    if len(es)>=2:
        #use the recent vs average compression ratio
        #(add value to smooth things out a bit, so very low compression ratios don't skew things)
        ascore, rscore = calculate_timesize_weighted_average_score(es)
        bump = 0
        if ascore>rscore:
            #raise the quality
            #only if there is no backlog:
            if packets_backlog==0:
                smooth = 150
                bump = logp((float(smooth+ascore)/(smooth+rscore)))-1.0
        else:
            #lower the quality
            #more so if the compression is not doing very well:
            mult = (1000 + rscore)/2000.0           #mult should be in the range 0.5 to ~1.0
            smooth = 50
            bump = -logp((float(smooth+rscore)/(smooth+ascore))-1.0) * mult
        target += bump
        info["compression-ratio"] = ascore, rscore, int(100*bump)
    if len(global_statistics.client_latency)>0 and global_statistics.recent_client_latency>0:
        #if the latency is too high, lower quality target:
        latency_q = 3.0 * statistics.target_latency / global_statistics.recent_client_latency
        target = min(target, latency_q)
        info["latency"] = int(100.0*latency_q)
    target = min(1.0, max(0.0, target))
    if min_speed>0:
        #discount the quality more aggressively if we have speed requirements to satisfy:
        #ie: for min_speed=50:
        #target=1.0   -> target=1.0
        #target=0.8   -> target=0.51
        #target=0.5   -> target=0.125
        #target=0     -> target=0
        target = target ** ((100.0 + 4*min_speed)/100.0)
    #raise the quality when there are not many recent damage events:
    ww, wh = window_dimensions
    if ww>0 and wh>0:
        now = monotonic_time()
        damage_pixel_count = dict((lim, sum([w*h for t,_,_,w,h in list(statistics.last_damage_events) if t>=now-lim and t<now-lim+1])) for lim in range(1,11))
        pixl5 = sum(v for lim,v in damage_pixel_count.items() if lim<=5)
        pixn5 = sum(v for lim,v in damage_pixel_count.items() if lim>5)
        pctpixdamaged = float(pixl5)/(ww*wh)
        log("get_target_quality: target=%s (window %ix%i) pctpixdamaged=%i%%, dpc=%s", target, ww, wh, pctpixdamaged*100, damage_pixel_count)
        if pctpixdamaged<=0.5:
            target = min(1.0, target + (1.0-pctpixdamaged*2))
        if pixl5<pixn5:
            target = sqrt(target)
    #apply min-quality:
    mq = min(100.0, max(min_quality, 0.0))
    target_quality = mq + (100.0-mq) * target
    return info, target_quality
