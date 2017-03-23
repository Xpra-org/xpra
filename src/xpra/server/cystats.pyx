# coding=utf8
# This file is part of Xpra.
# Copyright (C) 2012 - 2017 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

#!python
#cython: boundscheck=False, wraparound=False, cdivision=True

import time
from xpra.monotonic_time cimport monotonic_time

cdef extern from "math.h":
    double log(double x)

from math import sqrt
def logp(double x):
    return log(1.0+x)*1.4426950408889634

cdef inline double clogp(double x):
    return log(1.0+x)*1.4426950408889634

SMOOTHING_NAMES = {sqrt: "sqrt", logp: "logp"}
def smn(fn):
    return str(SMOOTHING_NAMES.get(fn, fn))


def calculate_time_weighted_average(data):
    """
        Given a list of items of the form [(event_time, value)],
        this method calculates a time-weighted average where
        recent values matter a lot more than more ancient ones.
    """
    assert len(data)>0
    cdef double now = monotonic_time()
    cdef double tv = 0.0
    cdef double tw = 0.0
    cdef double rv = 0.0
    cdef double rw = 0.0
    cdef double event_time
    cdef double value
    cdef double delta
    cdef double w
    for event_time, value in data:
        #newer matter more:
        delta = now-event_time
        w = 1.0/(1.0+delta)
        tv += value*w
        tw += w
        w = 1.0/(0.1+delta**2)
        rv += value*w
        rw += w
    return tv / tw, rv / rw

def time_weighted_average(data, double min_offset=0.1, double rpow=2.0):
    """
        Given a list of items of the form [(event_time, value)],
        this method calculates a time-weighted average where
        recent values matter a lot more than more ancient ones.
        We take the "rpow" power of the time offset.
        (defaults to 2, which means we square it)
    """
    assert len(data)>0
    cdef double now = monotonic_time()              #@DuplicatedSignature
    cdef double tv = 0.0                            #@DuplicatedSignature
    cdef double tw = 0.0                            #@DuplicatedSignature
    cdef double w                                   #@DuplicatedSignature
    cdef double delta                               #@DuplicatedSignature
    for event_time, value in data:
        delta = now-event_time
        assert delta>=0, "invalid event_time=%s, now=%s, delta=%s" % (event_time, now, delta)
        w = 1.0/(min_offset+delta**rpow)
        tv += value*w
        tw += w
    return tv / tw

def calculate_timesize_weighted_average_score(data):
    """
        This is a time weighted average where the size
        of each record also gives it a weight boost.
        This is to prevent small packets from skewing the average.
        Data format: (event_time, size, value)
    """
    cdef double size_avg = sum(x for _, x, _ in data)/len(data)
    cdef double now = monotonic_time()              #@DuplicatedSignature
    cdef double tv = 0.0                            #@DuplicatedSignature
    cdef double tw = 0.0                            #@DuplicatedSignature
    cdef double rv = 0.0                            #@DuplicatedSignature
    cdef double rw = 0.0                            #@DuplicatedSignature
    cdef double event_time                          #@DuplicatedSignature
    cdef int size
    cdef int value
    cdef double pw
    cdef double w                                   #@DuplicatedSignature
    cdef double delta                               #@DuplicatedSignature
    for event_time, size, value in data:
        if value<0:
            continue        #invalid record
        delta = now-event_time
        pw = clogp(size/size_avg)
        w = pw/(1.0+delta)*size
        tv += w*value
        tw += w
        w = pw/(0.1+delta**2)*size
        rv += w*value
        rw += w
    return int(tv / tw), int(rv / rw)

def calculate_timesize_weighted_average(data, float sizeunit=1.0):
    """
        This is a time weighted average where the size
        of each record also gives it a weight boost.
        This is to prevent small packets from skewing the average.
        Data format: (event_time, size, elapsed_time)
    """
    cdef double size_avg = sum(x for _, x, _ in data)/len(data)
    cdef double now = monotonic_time()              #@DuplicatedSignature
    cdef double tv = 0.0                            #@DuplicatedSignature
    cdef double tw = 0.0                            #@DuplicatedSignature
    cdef double rv = 0.0                            #@DuplicatedSignature
    cdef double rw = 0.0                            #@DuplicatedSignature
    cdef double event_time                          #@DuplicatedSignature
    cdef double size
    cdef double size_ps
    cdef double elapsed_time
    cdef double pw
    cdef double w                                   #@DuplicatedSignature
    cdef double delta                               #@DuplicatedSignature
    for event_time, size, elapsed_time in data:
        if elapsed_time<=0:
            continue        #invalid record
        delta = now-event_time
        pw = clogp(size/size_avg)
        size_ps = max(1, size*sizeunit/elapsed_time)
        w = pw/(1.0+delta)
        tv += w*size_ps
        tw += w
        w = pw/(0.1+delta**2)
        rv += w*size_ps
        rw += w
    return float(tv / tw), float(rv / rw)

def calculate_for_target(metric, float target_value, float avg_value, float recent_value, float aim=0.5, float div=1.0, float slope=0.1, smoothing=logp, float weight_multiplier=1.0):
    """
        Calculates factor and weight to try to bring us closer to 'target_value'.

        The factor is a function of how far the 'recent_value' is from it,
        and of how things are progressing (better or worse than average),
        'aim' controls the proportion of each. (at 0.5 it is an average of both,
        the closer to 0 the more target matters, the closer to 1.0 the more average matters)
    """
    assert aim>0.0 and aim<1.0
    #target factor: how far are we from 'target'
    cdef double d = float(div)
    cdef double target_factor = (float(recent_value)/d)/(slope+float(target_value)/d)
    #average factor: how far are we from the 'average'
    cdef double avg_factor = (float(recent_value)/d)/(slope+float(avg_value)/d)
    #aimed average: combine the two factors above with the 'aim' weight distribution:
    cdef double aimed_average = target_factor*(1.0-aim) + avg_factor*aim
    factor = smoothing(aimed_average)
    weight = smoothing(max(0.0, 1.0-factor, factor-1.0)) * weight_multiplier
    info = {"avg"       : int(1000.0*avg_value),
            "recent"    : int(1000.0*recent_value),
            "target"    : int(1000.0*target_value),
            "aim"       : int(1000.0*aim),
            "aimed_avg" : int(1000.0*aimed_average),
            "div"       : int(1000.0*div),
            "smoothing" : smn(smoothing),
            "weight_multiplier" : int(1000.0*weight_multiplier),
            }
    return metric, info , factor, weight

def calculate_for_average(metric, float avg_value, float recent_value, float div=1.0, float weight_offset=0.5, float weight_div=1.0):
    """
        Calculates factor and weight based on how far we are from the average value.
        This is used by metrics for which we do not know the optimal target value.
    """
    cdef double avg = avg_value/div
    cdef double recent = recent_value/div
    cdef double factor = clogp(recent/avg)
    cdef double weight = max(0, max(factor, 1.0/factor)-1.0+weight_offset)/weight_div
    info = {"avg"   : int(1000.0*avg),
            "recent": int(1000.0*recent)}
    return  metric, info, float(factor), float(weight)

def queue_inspect(metric, time_values, float target=1.0, float div=1.0, smoothing=logp):
    """
        Given an historical list of values and a current value,
        figure out if things are getting better or worse.
    """
    #inspect a queue size history: figure out if things are better or worse than before
    if len(time_values)==0:
        return  metric, {}, 1.0, 0.0
    avg, recent = calculate_time_weighted_average(list(time_values))
    weight_multiplier = sqrt(max(avg, recent) / div / target)
    return  calculate_for_target(metric, target, avg, recent, aim=0.25, div=div, slope=1.0, smoothing=smoothing, weight_multiplier=weight_multiplier)
