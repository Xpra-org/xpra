# This file is part of Xpra.
# Copyright (C) 2018 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.log import Logger
from xpra.scripts.config import TRUE_OPTIONS

log = Logger("scaling")


def parse_scaling(desktop_scaling, root_w, root_h, min_scaling=0.1, max_scaling=8):
    log("parse_scaling(%s)", (desktop_scaling, root_w, root_h, min_scaling, max_scaling))
    if desktop_scaling in TRUE_OPTIONS:
        return 1, 1
    if desktop_scaling.startswith("auto"):
        #figure out if the command line includes settings to use for auto mode:
        #here are our defaults:
        limits = ((3960, 2160, 1, 1),           #100% no auto scaling up to 4k
                  (7680, 4320, 1.25, 1.25),     #125%
                  (8192, 8192, 1.5, 1.5),       #150%
                  (16384, 16384, 5.0/3, 5.0/3), #166%
                  (32768, 32768, 2, 2),
                  (65536, 65536, 4, 4),
                  )         #200% if higher (who has this anyway?)
        if desktop_scaling=="auto":
            pass
        elif desktop_scaling.startswith("auto:"):
            limstr = desktop_scaling[5:]    #ie: '1920x1080:1,2560x1600:1.5,...
            limp = limstr.split(",")
            limits = []
            for l in limp:
                try:
                    ldef = l.split(":")
                    assert len(ldef)==2, "could not find 2 parts separated by ':' in '%s'" % ldef
                    dims = ldef[0].split("x")
                    assert len(dims)==2, "could not find 2 dimensions separated by 'x' in '%s'" % ldef[0]
                    x, y = int(dims[0]), int(dims[1])
                    scaleparts = ldef[1].replace("*", "x").replace("/", "x").split("x")
                    assert len(scaleparts)<=2, "found more than 2 scaling dimensions!"
                    if len(scaleparts)==1:
                        sx = sy = float(scaleparts[0])
                    else:
                        sx = float(scaleparts[0])
                        sy = float(scaleparts[1])
                    limits.append((x, y, sx, sy))
                    log("parsed desktop-scaling auto limits: %s", limits)
                except Exception as e:
                    log.warn("Warning: failed to parse limit string '%s':", l)
                    log.warn(" %s", e)
                    log.warn(" should use the format WIDTHxHEIGTH:SCALINGVALUE")
        else:
            log.warn("Warning: invalid auto attributes '%s'", desktop_scaling[5:])
        sx, sy = 1, 1
        matched = False
        for mx, my, tsx, tsy in limits:
            if root_w*root_h<=mx*my:
                sx, sy = tsx, tsy
                matched = True
                break
        log("matched=%s : %sx%s with limits %s: %sx%s", matched, root_w, root_h, limits, sx, sy)
        return sx,sy
    def parse_item(v):
        div = 1
        try:
            if v.endswith("%"):
                div = 100
                v = v[:-1]
        except:
            pass
        if div==1:
            try:
                return int(v)       #ie: desktop-scaling=2
            except:
                pass
        try:
            return float(v)/div     #ie: desktop-scaling=1.5
        except:
            pass
        #ie: desktop-scaling=3/2, or desktop-scaling=3:2
        pair = v.replace(":", "/").split("/", 1)
        try:
            return float(pair[0])/float(pair[1])
        except:
            pass
        log.warn("Warning: failed to parse scaling value '%s'", v)
        return None
    if desktop_scaling.find("x")>0 and desktop_scaling.find(":")>0:
        log.warn("Warning: found both 'x' and ':' in desktop-scaling fixed value")
        log.warn(" maybe the 'auto:' prefix is missing?")
        return 1, 1
    #split if we have two dimensions: "1600x1200" -> ["1600", "1200"], if not: "2" -> ["2"]
    values = desktop_scaling.replace(",", "x").split("x", 1)
    x = parse_item(values[0])
    if x is None:
        return 1, 1
    if len(values)==1:
        #just one value: use the same for X and Y
        y = x
    else:
        y = parse_item(values[1])
        if y is None:
            return 1, 1
    log("parse_scaling(%s) parsed items=%s", desktop_scaling, (x, y))
    #normalize absolute values into floats:
    if x>max_scaling or y>max_scaling:
        log(" normalizing dimensions to a ratio of %ix%i", root_w, root_h)
        x = float(x / root_w)
        y = float(y / root_h)
    if x<min_scaling or y<min_scaling or x>max_scaling or y>max_scaling:
        log.warn("Warning: scaling values %sx%s are out of range", x, y)
        return 1, 1
    log("parse_scaling(%s)=%s", desktop_scaling, (x, y))
    return x, y
