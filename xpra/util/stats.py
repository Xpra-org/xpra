# This file is part of Xpra.
# Copyright (C) 2012 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

# Simple statistical functions

import math
from collections.abc import Sequence


def to_std_unit(v, unit=1000):
    if v >= unit ** 3:
        return "G", v // (unit ** 3)
    if v >= unit ** 2:
        return "M", v // (unit ** 2)
    if v >= unit:
        return "K", v // unit
    return "", v


def std_unit(v, unit=1000) -> str:
    unit, value = to_std_unit(v, unit)
    return "%s%s" % (int(value), unit)


def std_unit_dec(v):
    unit, value = to_std_unit(v * 10.0)
    if value >= 100 or value <= 1:
        unit, value = to_std_unit(v)
        return "%s%s" % (int(value), unit)
    if int(value) % 10 == 0:
        return "%s%s" % (int(value // 10), unit)
    return "%s%s" % (int(value) / 10.0, unit)


def absolute_to_diff_values(in_data):
    """ Given a list of values, return a new list
        containing the incremental diff between each value
        ie: [0,2,2,10] -> [2,0,8]
    """
    last_value = None
    data = []
    for x in in_data:
        if last_value is not None:
            data.append(x - last_value)
        last_value = x
    return data


def values_to_scaled_values(data: Sequence[float | int],
                            scale_unit=10,
                            min_scaled_value=10,
                            num_values=20,
                            ) -> tuple[float, list[float | int | None]]:
    # print("values_to_scaled_values(%s, %s, %s)" % (data, scale_unit, num_values))
    if not data:
        return 0, []
    max_v = max(data)
    # pad with None values:
    if len(data) < num_values:
        if not isinstance(data, list):
            data = list(data)
        for _ in range(num_values - len(data)):
            data.insert(0, None)
    scale = 1
    assert scale_unit > 1
    while scale * scale_unit * min_scaled_value <= max_v:
        scale *= scale_unit
    if scale == 1:
        return scale, data
    sdata: list[float | None] = []
    for value in data:
        if value is None:
            sdata.append(None)
        else:
            sdata.append(float(value) / scale)
    return scale, sdata


def values_to_diff_scaled_values(data, scale_unit=10, min_scaled_value=10, num_values=20):
    return values_to_scaled_values(absolute_to_diff_values(data),
                                   scale_unit=scale_unit, min_scaled_value=min_scaled_value, num_values=num_values)


def get_weighted_list_stats(weighted_values, show_percentile=False):
    values = tuple(x[0] for x in weighted_values)
    if not values:
        return {}
    # weighted mean:
    tw = 0
    tv = 0
    for v, w in weighted_values:
        tw += w
        tv += v * w
    avg = tv / tw
    stats = {
        "min": int(min(values)),
        "max": int(max(values)),
        "avg": int(avg),
    }
    if show_percentile:
        # percentile
        svalues = sorted(values)
        for i in range(1, 10):
            pct = i * 10
            index = len(values) * i // 10
            stats["%ip" % pct] = int(svalues[index])
    return stats


def find_invpow(x, n):
    """Finds the integer component of the n'th root of x,
    an integer such that y ** n <= x < (y + 1) ** n.
    """
    high = 1.0
    while high ** n < x:
        high *= 2
    low = high / 2
    mid = low
    while low < high:
        mid = (low + high) // 2
        if low < mid and mid ** n < x:
            low = mid
        elif high > mid and mid ** n > x:
            high = mid
        else:
            return mid
    return mid + 1


def get_list_stats(in_values, show_percentile=(5, 8, 9), show_dev=False):
    # this may be backed by a deque/list whichi is used by other threads
    # so make a copy before use:
    values = tuple(in_values)
    if not values:
        return {}
    # arithmetic mean
    avg = sum(values) / len(values)
    lstats = {
        "cur": int(values[-1]),
        "min": int(min(values)),
        "max": int(max(values)),
        "avg": int(avg),
    }
    if show_dev:
        p = 1  # geometric mean
        h = 0  # harmonic mean
        var = 0  # variance
        counter = 0
        for x in values:
            if x != 0:
                p *= x
                h += 1.0 / x
                counter += 1
            var += (x - avg) ** 2
        # standard deviation:
        std = math.sqrt(var / len(values))
        lstats["std"] = int(std)
        if avg != 0:
            # coefficient of variation
            lstats["cv_pct"] = int(100.0 * std / avg)
        if counter > 0 and p < float('inf'):
            # geometric mean
            try:
                v = int(math.pow(p, 1.0 / counter))
            except (ValueError, OverflowError):
                v = find_invpow(p, counter)
            lstats["gm"] = v
        if h != 0:
            # harmonic mean
            lstats["h"] = int(counter / h)
    if show_percentile:
        # percentile
        svalues = sorted(values)
        for i in show_percentile:
            assert 0 < i < 10
            pct = i * 10
            index = len(values) * i // 10
            lstats["%ip" % pct] = int(svalues[index])
    return lstats
