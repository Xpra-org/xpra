#!/usr/bin/env python

from xpra.maths import values_to_diff_scaled_values

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

def main():
	test_values_to_diff_scaled_values()


if __name__ == "__main__":
	main()
