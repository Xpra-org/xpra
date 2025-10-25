# This file is part of Xpra.
# Copyright (C) 2011 Serviware (Arthur Huillet, <ahuillet@serviware.com>)
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
from time import monotonic
from typing import Any, Deque
from collections.abc import Sequence

from collections import deque
from xpra.common import Self, MIN_VREFRESH, MAX_VREFRESH
from xpra.util.stats import get_list_stats
from xpra.log import Logger

# how many historical records to keep
# for the various statistics we collect:
# (cannot be lower than DamageBatchConfig.MAX_EVENTS)
NRECS: int = 100

log = Logger("damage")


def ival(key, default: int, minv: int | None = 0, maxv: int | None = None) -> int:
    v = os.environ.get(f"XPRA_BATCH_{key}")
    if v is None:
        return default
    try:
        iv = int(v)
        if minv is not None and iv < minv:
            log.warn("value for %s is too small: %s (minimum is %s)", key, iv, minv)
            return minv
        if maxv is not None and iv > maxv:
            log.warn("value for %s is too high: %s (maximum is %s)", key, iv, maxv)
            return maxv
        return iv
    except Exception as e:
        log.warn("failed to parse value '%s' for %s: %s", v, key, e)
        return default


ALWAYS = ival("ALWAYS", 0, 0, 1) == 1
MAX_EVENTS = ival("MAX_EVENTS", min(50, NRECS), 10)  # maximum number of damage events
MAX_PIXELS = ival("MAX_PIXELS", 1024 * 1024 * MAX_EVENTS)  # small screen at MAX_EVENTS frames
TIME_UNIT = ival("TIME_UNIT", 1, 1, 1000)  # per second
MIN_DELAY = ival("MIN_DELAY", 16, 0, 1000)  # assume 60fps 1000/60=16.66
START_DELAY = ival("START_DELAY", 50, 1, 1000)
MAX_DELAY = ival("MAX_DELAY", 500, 1, 15000)
EXPIRE_DELAY = ival("EXPIRE_DELAY", 250, 10, 1000)
TIMEOUT_DELAY = ival("TIMEOUT_DELAY", 15000, 100, 100000)


class DamageBatchConfig:
    """
    Encapsulate all the damage batching configuration into one object.
    """
    __slots__ = (
        "wid", "always", "max_events", "max_pixels", "time_unit",
        "min_delay", "max_delay", "timeout_delay", "expire_delay",
        "start_delay", "delay", "delay_per_megapixel",
        "saved", "locked",
        "last_event", "last_delays", "last_delay", "last_actual_delays", "last_actual_delay",
        "last_updated", "factors",
    )

    def __init__(self):
        self.wid: int = 0
        self.always: bool = ALWAYS
        self.max_events: int = MAX_EVENTS
        self.max_pixels: int = MAX_PIXELS
        self.time_unit: int = TIME_UNIT
        self.min_delay: int = MIN_DELAY
        self.max_delay: int = MAX_DELAY
        self.timeout_delay: int = TIMEOUT_DELAY
        self.expire_delay: int = EXPIRE_DELAY
        self.start_delay: int = START_DELAY
        self.delay: int = START_DELAY
        self.delay_per_megapixel: int = -1
        self.saved: int = START_DELAY
        self.locked: bool = False  # to force a specific delay
        self.last_event: int = 0
        # the delays we have tried to use (milliseconds)
        self.last_delays: Deque[tuple[float, int]] = deque(maxlen=64)
        self.last_delay = None
        # the delays we actually used (milliseconds)
        self.last_actual_delays: Deque[tuple[float, int]] = deque(maxlen=64)
        self.last_actual_delay = None
        self.last_updated: int = 0
        # the metrics derived from statistics which we use for calculating the new batch delay:
        # (see batch delay calculator)
        self.factors: Sequence[tuple[str, dict, int, int]] = ()

    def cleanup(self) -> None:
        self.factors = ()

    def get_info(self) -> dict[str, Any]:
        info: dict[str, Any] = {
            "min-delay": self.min_delay,
            "max-delay": self.max_delay,
            "expire": self.expire_delay,
            "timeout-delay": self.timeout_delay,
            "locked": self.locked,
        }
        if self.delay_per_megapixel >= 0:
            info["normalized"] = self.delay_per_megapixel
        if self.last_event > 0:
            info["last-event"] = int(monotonic() - self.last_event)
        if self.locked:
            info["delay"] = self.delay
        else:
            ld = tuple(x[1] for x in tuple(self.last_delays))
            if ld:
                ls = get_list_stats(ld)
                ldv = self.last_delay
                if ldv:
                    ls["last"] = ldv[1]  # pylint: disable=unsubscriptable-object
                info["delay"] = ls
            lad = tuple(x[1] for x in tuple(self.last_actual_delays))
            if lad:
                ls = get_list_stats(lad, show_percentile=(9,))
                ladv = self.last_actual_delay
                if ladv:
                    ls["last"] = ladv[1]  # pylint: disable=unsubscriptable-object
                info["actual_delays"] = ls
            for name, details, factor, weight in self.factors:
                fdetails = details.copy()
                fdetails["factor"] = round(100.0 * factor)
                fdetails["weight"] = round(100.0 * weight)
                info[name] = fdetails
        return info

    def match_vrefresh(self, vrefresh: int = 60) -> None:
        if MIN_VREFRESH <= vrefresh <= MAX_VREFRESH:
            # looks like a valid vrefresh value, use it:
            ms_per_frame = max(5, 1000 // vrefresh)
            self.min_delay = max(self.min_delay, ms_per_frame)
            log("match_vrefresh(%s) min_delay=%s", vrefresh, self.min_delay)

    def clone(self) -> Self:
        c = DamageBatchConfig()
        for x in (
                "always", "max_events", "max_pixels", "time_unit",
                "min_delay", "max_delay", "timeout_delay", "start_delay", "delay", "expire_delay",
        ):
            setattr(c, x, getattr(self, x))
        return c

    def __repr__(self):
        return f"DamageBatchConfig({self.wid:#x})"
