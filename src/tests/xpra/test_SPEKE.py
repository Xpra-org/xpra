#!/usr/bin/env python

import hashlib
from Crypto.Util.number import getStrongPrime, bytes_to_long
from Crypto.Random import random

def test_SPEKE():
	password = "secret"
	p = getStrongPrime(768)
	h = hashlib.sha1()
	#https://build.opensuse.org/package/view_file?file=pycrypto-2.6-elgamal.patch&package=python-crypto.openSUSE_11.4_Update&project=openSUSE%3AMaintenance%3A564&rev=1fe551f41425aa7d6cb7bca6de778168
	h.update(password)
	print("hash(%s)=%s=%s" % (password, h.hexdigest(), bytes_to_long(h.digest())))
	sq = bytes_to_long(h.digest())**2
	print("hash^2=%s" % sq)
	g = sq % p
	print("g=%s" % g)
	ga = 0
	#choose values sufficiently large, but not too large
	#as this would slow down calculations too much!
	MIN_I = 2**12
	MAX_I = 2**13
	while ga<=2 or ga>=p-2:
		a = random.randint(MIN_I, MAX_I)
		print("a=%s" % a)
		ga = (g**a) % p
		print("(g**a)%%p=%s" % ga)
	gb = 0
	while gb<=2 or gb>=p-2:
		b = random.randint(MIN_I, MAX_I)
		print("b=%s" % b)
		gb = (g**b) % p
		print("(g**b)%%p=%s" % gb)
	ak = (gb**a) % p
	print("aK=%s" % ak)
	bk = (ga**b) % p
	print("bK=%s" % bk)
	assert ak==bk

def main():
	test_SPEKE()


if __name__ == "__main__":
	main()
