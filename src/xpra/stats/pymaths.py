# coding=utf8
# This file is part of Parti.
# Copyright (C) 2012 Antoine Martin <antoine@devloop.org.uk>
# Parti is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import time
from xpra.stats.base import dec3

from math import log as mathlog
def logp(x):
    return mathlog(1.0+x)/4.0

def calculate_time_weighted_average(data):
    """
        Given a list of items of the form [(event_time, value)],
        this method calculates a time-weighted average where
        recent values matter a lot more than more ancient ones.
    """
    assert len(data)>0
    now = time.time()
    tv, tw, rv, rw = 0.0, 0.0, 0.0, 0.0
    for event_time, value in data:
        #newer matter more:
        dt = now-event_time
        w = 1.0/(1.0+dt)
        tv += value*w
        tw += w
        w = 1.0/(0.1+dt**2)
        rv += value*w
        rw += w
    return tv / tw, rv / rw

def time_weighted_average(data, rpow=2):
    """
        Given a list of items of the form [(event_time, value)],
        this method calculates a time-weighted average where
        recent values matter a lot more than more ancient ones.
        We take the "rpow" power of the time offset.
        (defaults to 2, which means we square it)
    """
    assert len(data)>0
    now = time.time()
    tv, tw = 0.0, 0.0
    for event_time, value in data:
        w = 1.0/(0.1+(now-event_time)**rpow)
        tv += value*w
        tw += w
    return tv / tw

def calculate_timesize_weighted_average(data, sizeunit=1.0):
    """
        This is a time weighted average where the size
        of each record also gives it a weight boost.
        This is to prevent small packets from skewing the average.
        Data format: (event_time, size, elapsed_time)
    """
    size_avg = sum([x for _, x, _ in data])/len(data)
    now = time.time()
    tv, tw, rv, rw = 0.0, 0.0, 0.0, 0.0
    for event_time, size, elapsed_time in data:
        if elapsed_time<=0:
            continue        #invalid record
        pw = logp(size/size_avg)
        size_ps = max(1, size*sizeunit/elapsed_time)
        w = pw/(1.0+(now-event_time))
        tv += w*size_ps
        tw += w
        w = pw/(0.1+(now-event_time)**2)
        rv += w*size_ps
        rw += w
    return tv / tw, rv / rw

def calculate_for_target(msg_header, target_value, avg_value, recent_value, aim=0.5, div=1.0, slope=0.1, smoothing=logp, weight_multiplier=1.0):
    """
        Calculates factor and weight to try to bring us closer to 'target_value'.

        The factor is a function of how far the 'recent_value' is from it,
        and of how things are progressing (better or worse than average),
        'aim' controls the proportion of each. (at 0.5 it is an average of both,
        the closer to 0 the more target matters, the closer to 1.0 the more average matters)
    """
    assert aim>0.0 and aim<1.0
    #target factor: how far are we from 'target'
    d = float(div)
    target_factor = (float(recent_value)/d)/(slope+float(target_value)/d)
    #average factor: how far are we from the 'average'
    avg_factor = (float(recent_value)/d)/(slope+float(avg_value)/d)
    #aimed average: combine the two factors above with the 'aim' weight distribution:
    aimed_average = target_factor*(1.0-aim) + avg_factor*aim
    factor = smoothing(aimed_average)
    weight = smoothing(max(0.0, 1.0-factor, factor-1.0)) * weight_multiplier
    #if DEBUG_DELAY:
    #    msg += " [factors: target=%s, average=%s, aim=%s, aimed_average=%s]" % (dec2(target_factor), dec2(avg_factor), dec2(aim), dec2(aimed_average))
    return  "%s avg=%s, recent=%s, target=%s, aim=%s, aimed avg factor=%s, div=%s, s=%s" % (msg_header, dec3(avg_value), dec3(recent_value), dec3(target_value), aim, dec3(aimed_average), div, smoothing), factor, weight

def calculate_for_average(msg_header, avg_value, recent_value, div=1.0, weight_offset=0.5, weight_div=1.0):
    """
        Calculates factor and weight based on how far we are from the average value.
        This is used by metrics for which we do not know the optimal target value.
    """
    avg = avg_value/div
    recent = recent_value/div
    factor = logp(recent/avg)
    weight = max(0, max(factor, 1.0/factor)-1.0+weight_offset)/weight_div
    return  msg_header, factor, weight

def queue_inspect(msg_header, time_values, target=1.0, div=1.0, smoothing=logp):
    """
        Given an historical list of values and a current value,
        figure out if things are getting better or worse.
    """
    #inspect a queue size history: figure out if things are better or worse than before
    if len(time_values)==0:
        return  "%s (empty)" % msg_header, 1.0, 0.0
    avg, recent = calculate_time_weighted_average(list(time_values))
    return  calculate_for_target(msg_header, target, avg, recent, aim=0.25, div=div, slope=1.0, smoothing=smoothing)
