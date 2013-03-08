#!/usr/bin/env python

import random
import time
from xpra.maths import logp, values_to_diff_scaled_values, calculate_time_weighted_average, calculate_timesize_weighted_average, dec1

def test_values_to_diff_scaled_values():
	in_data = [1,2,4,10,50,51,62,73,81,85,89]
	for scale in 1, 100, 10000:
		scale_units = [10, 1000]
		if scale>10:
			scale_units.append(scale)
			scale_units.append(scale*1000)
		for scale_unit in scale_units:
			in_scaled = [x*scale for x in in_data]
			out_data = values_to_diff_scaled_values(in_scaled, scale_unit=scale_unit, num_values=len(in_scaled)-1)
			print("values_to_diff_scaled_values(%s,%s)=%s" % (in_scaled, scale_unit, out_data))

def test_calculate_timesize_weighted_average():
	#event_time, size, elapsed_time
	now = time.time()
	sample_size = 100000
	data = []
	t = now - sample_size
	for _ in xrange(sample_size):
		s = random.randint(1000, 10000)
		v = random.random()
		data.append((t, s, v))
		t += 1
	start = time.time()
	v = calculate_timesize_weighted_average(data)
	end = time.time()
	print("test_calculate_timesize_weighted_average(%s records)=%s" % (len(data), v))
	print("elapsed time: %sms" % dec1(1000*(end-start)))

def test_calculate_time_weighted_average():
	#event_time, value
	now = time.time()
	sample_size = 100000
	data = []
	t = now - sample_size
	for _ in xrange(sample_size):
		#v = random.randint(0, 10000)
		v = random.random()
		data.append((t, v))
		t += 1
	start = time.time()
	v = calculate_time_weighted_average(data)
	end = time.time()
	print("calculate_time_weighted_average(%s records)=%s" % (len(data), v))
	print("elapsed time: %sms" % dec1(1000*(end-start)))

def test_logp():
	start = time.time()
	for _ in xrange(100000):
		x = random.random()
		logp(x)
	end = time.time()
	print("logp:")
	print("elapsed time: %sms" % dec1(1000*(end-start)))


def main():
	#test_values_to_diff_scaled_values()
	test_calculate_time_weighted_average()
	test_calculate_timesize_weighted_average()
	test_logp()


if __name__ == "__main__":
	main()
