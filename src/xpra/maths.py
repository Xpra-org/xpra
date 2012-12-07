# coding=utf8
# This file is part of Parti.
# Copyright (C) 2012 Antoine Martin <antoine@devloop.org.uk>
# Parti is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

# Math functions used for inspecting/averaging lists of statistics
# see ServerSource

import time
from math import log as mathlog, sqrt, pow
sqrt2 = sqrt(2)
def logp(x):
    return mathlog(1.0+x, sqrt2)/2.0

def dec1(x):
    #for pretty debug output of numbers with one decimal
    return int(10.0*x)/10.0
def dec2(x):
    #for pretty debug output of numbers with two decimals
    return int(100.0*x)/100.0
def dec3(x):
    #for pretty debug output of numbers with three decimals
    return int(1000.0*x)/1000.0

def to_std_unit(v):
    if v>=1000*1000*1000:
        return "G", v/1000.0/1000.0/1000.0
    elif v>=1000*1000:
        return "M", v/1000.0/1000.0
    elif v>=1000:
        return "K", v/1000.0
    else:
        return "", v

def std_unit(v):
    unit, value = to_std_unit(v)
    return "%s%s" % (int(value), unit)

def std_unit_dec(v):
    unit, value = to_std_unit(v*10.0)
    return "%s%s" % (int(value)/10.0, unit)


def find_invpow(x, n):
    """Finds the integer component of the n'th root of x,
    an integer such that y ** n <= x < (y + 1) ** n.
    """
    high = 1
    while high ** n < x:
        high *= 2
    low = high/2
    while low < high:
        mid = (low + high) // 2
        if low < mid and mid**n < x:
            low = mid
        elif high > mid and mid**n > x:
            high = mid
        else:
            return mid
    return mid + 1

def absolute_to_diff_values(in_data):
    """ Given a list of values, return a new list
        containing the incremental diff between each value
        ie: [0,2,2,10] -> [2,0,8]
    """
    last_value = None
    data = []
    for x in in_data:
        if last_value is not None:
            data.append(x-last_value)
        last_value = x
    return data

def values_to_scaled_values(data, scale_unit=10, min_scaled_value=10, num_values=20):
    #print("values_to_scaled_values(%s, %s, %s)" % (data, scale_unit, num_values))
    if data is None or len(data)==0:
        return  0, data
    #pad with None values so we have at least num_values:
    if len(data)<num_values:
        for _ in range(num_values-len(data)):
            data.insert(0, None)
    max_v = max(data)
    scale = 1
    assert scale_unit>1
    while scale*scale_unit*min_scaled_value<=max_v:
        scale *= scale_unit
    if scale==1:
        return scale, data
    sdata = []
    for x in data:
        if x is None:
            sdata.append(None)
        else:
            sdata.append(x/scale)
    return scale, sdata

def values_to_diff_scaled_values(data, scale_unit=10, min_scaled_value=10, num_values=20):
    return values_to_scaled_values(absolute_to_diff_values(data), scale_unit=scale_unit, min_scaled_value=min_scaled_value, num_values=num_values)

def add_weighted_list_stats(info, basename, weighted_values, show_percentile=False):
    values = [x for x, _ in weighted_values]
    if len(values)==0:
        return
    info["%s.min" % basename] = int(min(values))
    info["%s.max" % basename] = int(max(values))
    #weighted mean:
    tw = 0
    tv = 0
    for v, w in weighted_values:
        tw += w
        tv += v * w
    avg = tv/tw
    info["%s.avg" % basename] = int(avg)
    if show_percentile:
        #percentile
        svalues = sorted(values)
        for i in range(1,10):
            pct = i*10
            index = len(values)*i//10
            info["%s.%sp" % (basename, pct)] = int(svalues[index])


def add_list_stats(info, basename, in_values, show_percentile=True):
    #this may be backed by a deque/list whichi is used by other threads
    #so make a copy before use:
    values = list(in_values)
    if len(values)==0:
        return
    info["%s.min" % basename] = int(min(values))
    info["%s.max" % basename] = int(max(values))
    #arithmetic mean
    avg = sum(values)/len(values)
    info["%s.avg" % basename] = int(avg)
    p = 1           #geometric mean
    h = 0           #harmonic mean
    var = 0         #variance
    counter = 0
    for x in values:
        if x!=0:
            p *= x
            h += 1.0/x
            counter += 1
        var += (x-avg)**2
    #standard deviation:
    std = sqrt(var/len(values))
    info["%s.std" % basename] = int(std)
    if avg!=0:
        #coefficient of variation
        info["%s.cv_pct" % basename] = int(100.0*std/avg)
    if counter>0 and p<float('inf'):
        #geometric mean
        try:
            v = int(pow(p, 1.0/counter))
        except OverflowError:
            v = find_invpow(p, counter)
        info["%s.gm" % basename] = v
    if h!=0:
        #harmonic mean
        info["%s.h" % basename] = int(counter/h)
    if show_percentile:
        #percentile
        svalues = sorted(values)
        for i in range(1,10):
            pct = i*10
            index = len(values)*i//10
            info["%s.%sp" % (basename, pct)] = int(svalues[index])


def calculate_time_weighted_average(data):
    """
        Given a list of items of the form [(event_time, value)],
        this method calculates a time-weighted average where
        recent values matter a lot more than more ancient ones.
        The 'recent' average is even more slanted towards recent values.
    """
    assert len(data)>0
    now = time.time()
    tv, tw, rv, rw = 0.0, 0.0, 0.0, 0.0
    for event_time, value in data:
        #newer matter more:
        w = 1.0/(1.0+(now-event_time))
        tv += value*w
        tw += w
        w = 1.0/(0.1+(now-event_time)**2)
        rv += value*w
        rw += w
    return tv / tw, rv / rw

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
