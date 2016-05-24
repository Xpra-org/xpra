# This file is part of Xpra.
# Copyright (C) 2008, 2009 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2011-2015 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.


from xpra.x11.gtk2.models import MAX_WINDOW_SIZE
MAX_ASPECT = 2**15-1

from xpra.log import Logger
log = Logger("x11", "window")


def sanitize_size_hints(size_hints):
    """
        Some applications may set nonsensical values,
        try our best to come up with something that can actually be used.
    """
    if size_hints is None:
        return
    for attr in ["min_aspect", "max_aspect"]:
        v = size_hints.get(attr)
        if v is not None:
            try:
                f = float(v)
            except:
                f = None
            if f is None or f<=0 or f>=MAX_ASPECT:
                log.warn("clearing invalid aspect hint value for %s: %s", attr, v)
                del size_hints[attr]
    for attr in ["min_aspect_ratio", "max_aspect_ratio"]:
        v = size_hints.get(attr)
        if v is not None:
            try:
                f = float(v[0])/float(v[1])
            except:
                f = None
            if f is None or f<=0 or f>=MAX_ASPECT:
                log.warn("clearing invalid aspect hint value for %s: %s", attr, v)
                del size_hints[attr]
    for attr in ["max_size", "min_size", "base_size", "resize_inc",
                 "min_aspect_ratio", "max_aspect_ratio"]:
        v = size_hints.get(attr)
        if v is not None:
            try:
                w,h = v
            except:
                w,h = None,None
            if (w is None or h is None) or w>=MAX_WINDOW_SIZE or h>=MAX_WINDOW_SIZE:
                log("clearing invalid size hint value for %s: %s", attr, v)
                del size_hints[attr]
    #if max-size is smaller than min-size (bogus), clamp it..
    mins = size_hints.get("min_size")
    maxs = size_hints.get("max_size")
    if mins is not None and maxs is not None:
        minw,minh = mins
        maxw,maxh = maxs
        if minw<=0 and minh<=0:
            #doesn't do anything
            size_hints["min_size"] = None
        if maxw<=0 or maxh<=0:
            #doesn't mak sense!
            size_hints["max_size"] = None
        if maxw<minw or maxh<minh:
            size_hints["min_size"] = max(minw, maxw), max(minh, maxh)
            size_hints["max_size"] = size_hints.min_size
            log.warn("invalid min_size=%s / max_size=%s changed to: %s / %s",
                     mins, maxs, size_hints["min_size"], size_hints["max_size"])
