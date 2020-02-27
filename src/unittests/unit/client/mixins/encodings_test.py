#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2019 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest

from xpra.util import AdHocStruct
from xpra.client.mixins.encodings import Encodings
from unit.client.mixins.clientmixintest_util import ClientMixinTest


class DisplayClientTest(ClientMixinTest):

	def test_encoding(self):
		opts = AdHocStruct()
		opts.encoding = ""
		opts.encodings = ["rgb", "png", "jpeg"]
		opts.quality = 1
		opts.min_quality = 20
		opts.speed = 0
		opts.min_speed = 20
		opts.video_scaling = "no"
		opts.video_decoders = []
		opts.csc_modules = []
		opts.video_encoders = []
		m = self._test_mixin_class(Encodings, opts, {
			"encodings" : ["rgb"],
			"encodings.core" : ["rgb32", "rgb24", "png"],
			"encodings.problematic" : [],
			"encoding" : ""
			})
		m.set_encoding("auto")
		def f(fn, err):
			try:
				fn()
			except Exception:
				pass
			else:
				raise Exception(err)
		def set_invalid_encoding():
			m.set_encoding("invalid")
		f(set_invalid_encoding, "should not be able to set encoding 'invalid'")
		#this will trigger a warning:
		m.set_encoding("jpeg")
		#quality:
		for q in (-1, 0, 1, 99, 100):
			m.quality = q
			m.send_quality()
		for q in (-2, 101):
			m.quality = q
			f(m.send_quality, "should not be able to send invalid quality %i" % q)
		#min-quality:
		for q in (-1, 0, 1, 99, 100):
			m.min_quality = q
			m.send_min_quality()
		for q in (-2, 101):
			m.min_quality = q
			f(m.send_min_quality, "should not be able to send invalid min-quality %i" % q)
		#speed:
		for s in (-1, 0, 1, 99, 100):
			m.speed = s
			m.send_speed()
		for s in (-2, 101):
			m.speed = s
			f(m.send_speed, "should not be able to send invalid speed %i" % s)
		#min-speed:
		for s in (-1, 0, 1, 99, 100):
			m.min_speed = s
			m.send_min_speed()
		for s in (-2, 101):
			m.min_speed = s
			f(m.send_min_speed, "should not be able to send invalid min-speed %i" % s)


def main():
	unittest.main()


if __name__ == '__main__':
	main()
