# coding=utf8
# This file is part of Parti.
# Copyright (C) 2012, 2013 Antoine Martin <antoine@devloop.org.uk>
# Parti is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

# Simple statistical functions

from math import sqrt, pow

def to_std_unit(v, unit=1000.0):
    if v>=unit**3:
        return "G", v/(unit**3)
    elif v>=unit**2:
        return "M", v/(unit**2)
    elif v>=unit:
        return "K", v/unit
    else:
        return "", v

def std_unit(v, unit=1000.0):
    unit, value = to_std_unit(v, unit)
    return "%s%s" % (int(value), unit)

def std_unit_dec(v):
    unit, value = to_std_unit(v*10.0)
    if value>=100:
        return "%s%s" % (int(value/10.0), unit)
    return "%s%s" % (int(value)/10.0, unit)


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

def add_list_stats(info, basename, in_values, show_percentile=[5, 8, 9], show_dev=False):
    #this may be backed by a deque/list whichi is used by other threads
    #so make a copy before use:
    values = list(in_values)
    if len(values)==0:
        return
    info["%s.cur" % basename] = int(values[-1])
    info["%s.min" % basename] = int(min(values))
    info["%s.max" % basename] = int(max(values))
    #arithmetic mean
    avg = sum(values)/len(values)
    info["%s.avg" % basename] = int(avg)
    if show_dev:
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
        for i in show_percentile:
            pct = i*10
            index = len(values)*i//10
            info["%s.%sp" % (basename, pct)] = int(svalues[index])
