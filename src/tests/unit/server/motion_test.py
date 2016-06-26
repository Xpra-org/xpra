#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2011-2014 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest
import time
from zlib import crc32

try:
	from xpra.server.window import motion
except ImportError:
	motion = None


class TestMotion(unittest.TestCase):

	def test_match_distance(self):
		def t(a1, a2, distance, matches):
			lines = motion.match_distance(a1, a2, distance)
			assert len(lines)==matches, "expected %i matches for distance=%i but got %i for a1=%s, a2=%s, result=%s" % (matches, distance, len(lines), a1, a2, lines)
		for N in (1, 10, 100):
			a = range(N)
			t(a, a, 0, N)		#identity: all match

			a = [0]*N
			t(a, a, 0, N)
			for M in range(N):
				t(a, a, M, N-M)

		#from a2 to a1: shift by -2, get 2 hits
		t([0, 1, 2, 3], [2, 3, 4, 5], -2, 2)
		N = 100
		a1 = range(N)
		for M in (1, 2, 10, 100):
			a2 = range(M, M+N)
			t(a1, a2, -M, N-abs(M))
			a2 = range(-M, N-M)
			t(a1, a2, M, N-abs(M))
		for M in (-10, -20):
			a2 = range(M, N+M)
			t(a1, a2, -M, N-abs(M))

	def test_consecutive_lines(self):
		def f(v):
			try:
				motion.consecutive_lines(v)
			except:
				pass
			else:
				raise Exception("consecutive_lines should have failed for value %s" % v)
		f(None)
		f("")
		f([])
		f(1)
		def t(v, e):
			r = motion.consecutive_lines(v)
			assert r==e, "expected %s but got %s for input=%s" % (e, r, v)
		t([5, 10], [(5, 1), (10, 1)])
		t([5], [(5, 1)])
		t([1,2,3], [(1,3)])
		t(range(100), [(0, 100),])
		t([1,2,3,100,200,201], [(1,3), (100, 1), (200, 2)])

	def test_calculate_distances(self):
		array1 = [crc32(str(x)) for x in (1234, "abc", 99999)]
		array2 = array1
		d = motion.calculate_distances(array1, array2, 1)
		assert len(d)==1 and d[0]==3

		array1 = range(0, 3)
		array2 = range(1, 4)
		d = motion.calculate_distances(array1, array2, 1)
		assert len(d)==1, "expected 1 match but got: %s" % d
		assert d.get(1)==2, "expected distance of 1 with 2 hits but got: %s" % d
		def cdf(v1, v2):
			try:
				motion.calculate_distances(v1, v2, 1)
			except:
				return
			raise Exception("calculate_distances should have failed for values: %s" % (v1, v2))
		cdf(None, None)
		cdf([], None)
		cdf(None, [])
		cdf([1, 2], [1])
		assert len(motion.calculate_distances([], [], 1))==0

		#performance:
		N = 4096
		start = time.time()
		array1 = range(N)
		array2 = [N*2-x*2 for x in range(N)]
		d = motion.calculate_distances(array1, array2, 1)
		end = time.time()
		print("distances for %ix%i took %.1fms" % (N, N, (end-start)*1000))


def main():
	if motion:
		unittest.main()


if __name__ == '__main__':
	main()
