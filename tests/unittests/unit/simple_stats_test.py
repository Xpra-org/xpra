#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2011 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest
from xpra.util.stats import (
    values_to_diff_scaled_values, get_list_stats, get_weighted_list_stats,
    to_std_unit, std_unit, std_unit_dec,
    find_invpow,
)


class TestSimpleStats(unittest.TestCase):

    def test_std_unit(self):
        assert to_std_unit(1000) == ("K", 1)
        assert to_std_unit(9999999) == ("M", 9)
        assert to_std_unit(10000000) == ("M", 10)
        assert to_std_unit(5000000000) == ("G", 5)
        assert to_std_unit(65536, 1024) == ("K", 64)
        assert to_std_unit(1048576, 1024) == ("M", 1)
        assert std_unit(0) == "0"
        assert std_unit(999) == "999"
        assert std_unit(1000) == "1K"
        assert std_unit_dec(9.59999999) == "9.5"
        assert std_unit_dec(5) == "5"
        assert std_unit_dec(20) == "20"
        assert std_unit_dec(100.59999999) == "100"

    def test_values_to_diff_scaled_values(self):
        assert values_to_diff_scaled_values([]) == (0, [])
        in_data = [1,2,4,10,50,51,62,73,81,85,89]
        for scale in 1, 100, 10000:
            scale_units = [10, 1000]
            if scale > 10:
                scale_units.append(scale)
                scale_units.append(scale*1000)
            for scale_unit in scale_units:
                in_scaled = [x*scale for x in in_data]
                oscale, out_data = values_to_diff_scaled_values(in_scaled, scale_unit=scale_unit, num_values=len(in_scaled)-1)
                assert oscale > 0
                # output will be a scaled multiple of:
                # [1, 2, 6, 40, 1, 11, 11, 8, 4, 4]
                assert out_data[1] / out_data[0] == 2        # 2/1
                assert out_data[3] / out_data[4] == 40        # 40/1
        # test padding:
        oscale, out_data = values_to_diff_scaled_values(in_data, scale_unit=10, num_values=100)
        assert oscale == 1
        assert all(out_data[i] is None for i in range(100-len(in_data)))

    def test_find_invpow(self):
        assert find_invpow(-1, 1) == 1
        assert find_invpow(-1, 0) == 1
        assert find_invpow(0, 0) == 1
        assert find_invpow(1, 1) == 0
        assert find_invpow(1, 0) == 0
        assert find_invpow(0, 1) == 0
        assert find_invpow(1000, 3) == 10
        assert find_invpow(9, 2) == 3
        assert find_invpow(2**32, 2) == 65535
        assert find_invpow(2**32+1, 2) == 65536
        assert find_invpow(2**32, 8) == 15
        assert find_invpow(2**32+1, 8) == 16

    def test_get_list_stats(self):
        assert get_list_stats([])=={}
        N = 100
        values = tuple(range(N))
        percentile = (5, 8, 9)
        lstats = get_list_stats(values, show_percentile=percentile, show_dev=True)
        assert lstats.get("max") == N-1
        assert lstats.get("min") == 0
        assert lstats.get("avg") == N//2-1
        assert lstats.get("cur") == N-1
        assert lstats.get("std") == 28
        assert lstats.get("cv_pct") == 58
        assert lstats.get("gm") == 37
        assert lstats.get("h") == 19
        for p in percentile:
            assert lstats.get(f"{p}0p") == p*10

    def test_get_weighted_list_stats(self):
        assert get_weighted_list_stats([]) == {}
        N = 10
        values = list((x, x % 2+1) for x in range(N))
        stats = get_weighted_list_stats(values, show_percentile=True)
        assert stats.get("min") == 0
        assert stats.get("max") == 9
        assert stats.get("avg") == 4
        percentile = range(1, 10)
        for p in percentile:
            assert stats.get(f"{p}0p")==p


def main():
    unittest.main()


if __name__ == '__main__':
    main()
