#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2011-2017 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest
import random

from xpra.os_util import monotonic_time
try:
	from xpra.server import cystats
except ImportError:
	cystats = None


class TestCystats(unittest.TestCase):

	def test_calculate_timesize_weighted_average(self):
		#event_time, size, elapsed_time
		now = monotonic_time()
		sample_size = 1000
		data = []
		t = now - sample_size
		for _ in range(sample_size):
			s = random.randint(1000, 10000)
			v = random.random()
			data.append((t, s, v))
			t += 1
		a, ra = cystats.calculate_timesize_weighted_average(data)
		assert 0<a and 0<ra
		#the calculations use the ratio of the size divided by the elapsed time,
		#so check that a predictable ratio gives the expected value:
		for x in (5, 1000):
			v = [(now, i*x, i) for i in range(1, 1000)]
			a, ra = cystats.calculate_timesize_weighted_average(v)
			#but we need to round to an int to compare
			self.assertEquals(x, int(round(a)))
			self.assertEquals(x, int(round(ra)))
		def t(v, ea, era):
			a, ra = cystats.calculate_timesize_weighted_average(v)
			self.assertEquals(int(round(a)), ea)
			self.assertEquals(int(round(ra)), era)
		#an old record won't make any difference
		#compared with one that was taken just now:
		for v in (1, 10, 10000):
			#1 day ago:
			t([(now-1000*60*60*24, 100*1000, 1000), (now, v*1000, 1000)], v, v)
			t([(now-1000*60*60*24, 1*1000, 1000), (now, v*1000, 1000)], v, v)
			#1 hour ago:
			t([(now-1000*60*60, 100*1000, 1000), (now, v*1000, 1000)], v, v)
			t([(now-1000*60*60, 1*1000, 1000), (now, v*1000, 1000)], v, v)
			#1 minute ago:
			t([(now-1000*60, 100*1000, 1000), (now, v*1000, 1000)], v, v)
			t([(now-1000*60, 1*1000, 1000), (now, v*1000, 1000)], v, v)
			#20 seconds ago:
			t([(now-1000*20, 100*1000, 1000), (now, v*1000, 1000)], v, v)
			t([(now-1000*20, 1*1000, 1000), (now, v*1000, 1000)], v, v)
		#but 100ms ago starts to make a difference:
		t([(now-100, 100*1000, 1000), (now, 50*1000, 1000)], 51, 50)
		t([(now-100, 1*1000, 1000), (now, 50*1000, 1000)], 50, 50)
		#if using the same time, then size matters more:
		v = [(now, 100*1000, 1000), (now, 50*1000, 1000)]
		a, ra = cystats.calculate_timesize_weighted_average(v)
		#recent is the same as "normal" average:
		self.assertEquals(int(round(a)), int(round(ra)))
		self.assertGreater(a, 75)
		#real data:
		v =[(1411278021.557095, 157684, 9110), (1411278022.23345, 3744, 1279), (1411278022.376621, 3744, 706),
			(1411278022.515456, 3744, 1302), (1411278023.013887, 78, 1342), (1411278043.707768, 78, 920),
			(1411278044.043399, 78, 1558), (1411278044.046686, 78, 1119), (1411278044.048169, 78, 1007),
			(1411278044.049807, 1716, 626), (1411278044.053967, 78, 2841), (1411278044.23714, 78, 1393),
			(1411278044.238555, 78, 2903), (1411278044.242623, 78, 1167), (1411278044.244426, 1716, 1032),
			(1411278044.245675, 78, 720), (1411278044.392009, 78, 784), (1411278044.392771, 78, 737),
			(1411278044.396293, 78, 911), (1411278044.397466, 1716, 772), (1411278044.398027, 78, 1234),
			(1411278044.538323, 78, 1200), (1411278044.539683, 78, 586), (1411278044.542575, 78, 1203),
			(1411278044.544646, 1716, 1129), (1411278044.546205, 78, 979), (1411278044.701881, 78, 901),
			(1411278044.703987, 78, 448), (1411278044.708965, 78, 474), (1411278044.711481, 1716, 1444),
			(1411278044.713157, 78, 1033), (1411278044.848487, 78, 860), (1411278044.850604, 78, 1172),
			(1411278044.857039, 78, 1367), (1411278044.858723, 1716, 1078), (1411278044.859743, 78, 1876),
			(1411278044.993883, 78, 824), (1411278044.99714, 78, 796), (1411278045.001942, 78, 714),
			(1411278045.002884, 1716, 744), (1411278045.004841, 78, 652), (1411278045.772856, 78, 652)]
		raw_v = [size/elapsed for _,size,elapsed in v]
		min_v = min(raw_v)
		max_v = max(raw_v)
		a, ra = cystats.calculate_timesize_weighted_average(v)
		self.assertLess(a, max_v)
		self.assertLess(ra, max_v)
		self.assertGreater(a, min_v)
		self.assertGreater(ra, min_v)

	def test_calculate_time_weighted_average(self):
		now = monotonic_time()
		sample_size = 100
		data = []
		t = now - sample_size
		for _ in range(sample_size):
			v = random.random()
			data.append((t, v))
			t += 1
		a, ra = cystats.calculate_time_weighted_average(data)
		assert 0<a<1 and 0<ra<1

	def test_logp(self):
		for _ in range(1000):
			x = random.random()
			v = cystats.logp(x)
			assert v>=0 and v<=1
		for x in (0, 1):
			v = cystats.logp(x)
			assert v>=0 and v<=1


def main():
	if cystats:
		unittest.main()

if __name__ == '__main__':
	main()
