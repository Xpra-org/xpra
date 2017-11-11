# -*- coding: utf-8 -*-
# This file is part of Xpra.
# Copyright (C) 2011 Serviware (Arthur Huillet, <ahuillet@serviware.com>)
# Copyright (C) 2010-2017 Antoine Martin <antoine@devloop.org.uk>
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

#how many historical records to keep
#for the various statistics we collect:
#(cannot be lower than DamageBatchConfig.MAX_EVENTS)
NRECS = 100

from collections import deque
from xpra.simple_stats import get_list_stats

import os


def ival(key, default, minv=0, maxv=None):
    try:
        v = os.environ.get("XPRA_BATCH_%s" % key)
        if v is None:
            return default
        iv = int(v)
        assert minv is None or minv<=iv, "value for %s is too small: %s (minimum is %s)" % (key, iv, minv)
        assert maxv is None or maxv>=iv, "value for %s is too high: %s (maximum is %s)" % (key, iv, maxv)
        return iv
    except Exception as e:
        from xpra.os_util import get_util_logger
        log = get_util_logger()
        log.warn("failed to parse value '%s' for %s: %s", v, key, e)
        return default


class DamageBatchConfig(object):
    """
    Encapsulate all the damage batching configuration into one object.
    """
    ALWAYS = ival("ALWAYS", 0, 0, 1)==1
    MAX_EVENTS = ival("MAX_EVENTS", min(50, NRECS), 10)         #maximum number of damage events
    MAX_PIXELS = ival("MAX_PIXELS", 1024*1024*MAX_EVENTS)       #small screen at MAX_EVENTS frames
    TIME_UNIT = ival("TIME_UNIT", 1, 1, 1000)                   #per second
    MIN_DELAY = ival("MIN_DELAY", 5, 0, 1000)                   #lower than 5 milliseconds does not make sense, just don't batch
    START_DELAY = ival("START_DELAY", 50, 1, 1000)
    MAX_DELAY = ival("MAX_DELAY", 500, 1, 15000)
    TIMEOUT_DELAY = ival("TIMEOUT_DELAY", 15000, 100, 100000)

    def __init__(self):
        self.wid = 0
        self.always = self.ALWAYS
        self.max_events = self.MAX_EVENTS
        self.max_pixels = self.MAX_PIXELS
        self.time_unit = self.TIME_UNIT
        self.min_delay = self.MIN_DELAY
        self.max_delay = self.MAX_DELAY
        self.timeout_delay = self.TIMEOUT_DELAY
        self.delay = self.START_DELAY
        self.saved = self.START_DELAY
        self.locked = False                             #to force a specific delay
        self.last_delays = deque(maxlen=64)             #the delays we have tried to use (milliseconds)
        self.last_actual_delays = deque(maxlen=64)      #the delays we actually used (milliseconds)
        self.last_updated = 0
        #the metrics derived from statistics which we use for calculating the new batch delay:
        #(see batch delay calculator)
        self.factors = ()

    def cleanup(self):
        self.factors = ()

    def get_info(self):
        info = {
            "min-delay"         : self.min_delay,
            "max-delay"         : self.max_delay,
            "timeout-delay"     : self.timeout_delay,
            "locked"            : self.locked,
            }
        if self.locked:
            info["delay"] = self.delay
        else:
            if len(self.last_delays)>0:
                batch_delays = [x for _,x in list(self.last_delays)]
                info["delay"] = get_list_stats(batch_delays)
            if len(self.last_actual_delays)>0:
                batch_delays = [x for _,x in list(self.last_actual_delays)]
                info["actual_delays"] = get_list_stats(batch_delays, show_percentile=[9])
            for name, details, factor, weight in self.factors:
                fdetails = details.copy()
                fdetails[""] = int(100.0*factor), int(100.0*weight)
                info[name] = fdetails
        return info


    def clone(self):
        c = DamageBatchConfig()
        for x in ["always", "max_events", "max_pixels", "time_unit",
                  "min_delay", "max_delay", "timeout_delay", "delay"]:
            setattr(c, x, getattr(self, x))
        return c

    def __repr__(self):
        return  "DamageBatchConfig(%i)" % (self.wid)
