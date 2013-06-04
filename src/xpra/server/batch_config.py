# coding=utf8
# This file is part of Xpra.
# Copyright (C) 2011 Serviware (Arthur Huillet, <ahuillet@serviware.com>)
# Copyright (C) 2010-2013 Antoine Martin <antoine@devloop.org.uk>
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

#how many historical records to keep
#for the various statistics we collect:
#(cannot be lower than DamageBatchConfig.MAX_EVENTS)
NRECS = 100

from xpra.deque import maxdeque

class DamageBatchConfig(object):
    """
    Encapsulate all the damage batching configuration into one object.
    """
    ALWAYS = False
    MAX_EVENTS = min(50, NRECS)         #maximum number of damage events
    MAX_PIXELS = 1024*1024*MAX_EVENTS   #small screen at MAX_EVENTS frames
    TIME_UNIT = 1                       #per second
    MIN_DELAY = 5                       #lower than 5 milliseconds does not make sense, just don't batch
    START_DELAY = 50
    MAX_DELAY = 15000
    RECALCULATE_DELAY = 0.04            #re-compute delay 25 times per second at most
                                        #(this theoretical limit is never achieved since calculations take time + scheduling also does)


    def __init__(self):
        self.always = self.ALWAYS
        self.max_events = self.MAX_EVENTS
        self.max_pixels = self.MAX_PIXELS
        self.time_unit = self.TIME_UNIT
        self.min_delay = self.MIN_DELAY
        self.max_delay = self.MAX_DELAY
        self.delay = self.START_DELAY
        self.last_delays = maxdeque(64)                 #the delays we have tried to use (milliseconds)
        self.last_actual_delays = maxdeque(64)          #the delays we actually used (milliseconds)
        self.last_updated = 0
        self.wid = 0

    def clone(self):
        c = DamageBatchConfig()
        for x in ["always", "max_events", "max_pixels", "time_unit",
                  "min_delay", "max_delay", "delay"]:
            setattr(c, x, getattr(self, x))
        return c

    def __str__(self):
        return  "DamageBatchConfig(wid=%s, always=%s, min=%s, max=%s, current=%s, max events=%s, max pixels=%s, time unit=%s)" % \
                (self.wid, self.always, self.min_delay, self.max_delay, self.delay, self.max_events, self.max_pixels, self.time_unit)
