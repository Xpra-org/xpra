#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2011-2014 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest
from xpra.simple_stats import values_to_diff_scaled_values


class TestSimpleStats(unittest.TestCase):

	def test_values_to_diff_scaled_values(self):
		in_data = [1,2,4,10,50,51,62,73,81,85,89]
		for scale in 1, 100, 10000:
			scale_units = [10, 1000]
			if scale>10:
				scale_units.append(scale)
				scale_units.append(scale*1000)
			for scale_unit in scale_units:
				in_scaled = [x*scale for x in in_data]
				oscale, out_data = values_to_diff_scaled_values(in_scaled, scale_unit=scale_unit, num_values=len(in_scaled)-1)
				assert oscale>0
				#output will be a scaled multiple of:
				#[1, 2, 6, 40, 1, 11, 11, 8, 4, 4]
				assert out_data[1] / out_data[0]==2		# 2/1
				assert out_data[3] / out_data[4]==40	# 40/1

def main():
	unittest.main()

if __name__ == '__main__':
	main()
