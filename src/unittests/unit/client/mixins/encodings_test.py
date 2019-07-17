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
		opts.encodings = ["rgb", "png"]
		opts.quality = 0
		opts.min_quality = 20
		opts.speed = 0
		opts.min_speed = 20
		opts.video_scaling = "no"
		opts.video_decoders = []
		opts.csc_modules = []
		opts.video_encoders = []
		self._test_mixin_class(Encodings, opts, {
			"encodings" : ["rgb"],
			"encodings.core" : ["rgb32", "rgb24", "png"],
			"encodings.problematic" : [],
			"encoding" : ""
			})

def main():
	unittest.main()


if __name__ == '__main__':
	main()
