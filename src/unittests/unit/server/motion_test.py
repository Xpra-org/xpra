#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2011-2014 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest
import time
from zlib import crc32

from xpra.util import envbool
try:
	from xpra.server.window import motion
except ImportError:
	motion = None


SHOW_PERF = envbool("XPRA_SHOW_PERF")


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
		if SHOW_PERF:
			print("calculate_distances %4i^2 in %5.1f ms" % (N, (end-start)*1000))

	def test_detect_motion(self):
		W, H, BPP = 1920, 1080, 4
		#W, H, BPP = 2, 4, 4
		LEN = W * H * BPP
		import numpy as np
		try:
			na1 = np.random.randint(2**63-1, size=LEN//8, dtype="int64")
		except TypeError as e:
			#older numpy version may not have dtype argument..
			#and may not accept 64-bit values
			print("skipping motion detection test")
			print(" because of incompatible numpy version: %s" % e)
			try:
				print(" numpy %s" % np.version.version)
			except:
				pass
			return
		def tobytes(a):
			try:
				return a.tobytes()
			except:
				#older versions of numpy (ie: centos7)
				return a.tostring()
		buf1 = tobytes(na1)
		ov1 = motion.CRC_Image(buf1, W, H, W*BPP, BPP)
		assert len(ov1)==H
		#make a new "image" shifted N lines:
		for N in (1, 20, 100):
			na2 = np.roll(na1, -N*W*BPP//8)
			buf2 = tobytes(na2)
			start = time.time()
			ov2 = motion.CRC_Image(buf2, W, H, W*BPP, BPP)
			end = time.time()
			if SHOW_PERF:
				print("\nCRC_Image %ix%i (%.1fMB) in %4.2f ms" % (W, H, len(buf2)//1024//1024, 1000.0*(end-start)))
			assert len(ov2)==H
			start = time.time()
			distances = motion.calculate_distances(ov1, ov2, min_score=1)
			end = time.time()
			if SHOW_PERF:
				print("calculate_distances %4i^2 in %5.2f ms" % (H, 1000.0*(end-start)))
			linecount = distances.get(N, 0)
			assert linecount>0, "could not find distance %i" % N
			assert linecount == (H-N), "expected to match %i lines but got %i" % (H-N, linecount)
		if False:
			import binascii
			print("na1:\n%s" % binascii.hexlify(tobytes(na1)))
			print("na2:\n%s" % binascii.hexlify(tobytes(na2)))
			np.set_printoptions(threshold=np.inf)
			print("na1:\n%s" % (na1, ))
			print("na2:\n%s" % (na2, ))
			print("ov1:\n%s" % (ov1, ))
			print("ov2:\n%s" % (ov2, ))

def main():
	if motion:
		unittest.main()


if __name__ == '__main__':
	main()
