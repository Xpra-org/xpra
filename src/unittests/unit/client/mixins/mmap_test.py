#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2018-2019 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest

from xpra.util import AdHocStruct
from xpra.client.mixins.mmap import MmapClient
from unit.client.mixins.clientmixintest_util import ClientMixinTest


class MixinsTest(ClientMixinTest):

	def test_mmap(self):
		opts = AdHocStruct()
		opts.mmap = "on"
		opts.mmap_group = False
		self._test_mixin_class(MmapClient, opts, {
			"mmap.enabled"		: True,
			})

	def make_caps(self, caps):
		d = ClientMixinTest.make_caps(self, caps)
		x = self.mixin
		d.update({
			"mmap.token"		: x.mmap_token,
			"mmap.token_bytes"	: x.mmap_token_bytes,
			"mmap.token_index"	: x.mmap_token_index,
			})
		return d


def main():
	unittest.main()


if __name__ == '__main__':
	main()
