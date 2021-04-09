#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2019-2020 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

#pylint: disable=line-too-long

import unittest

from xpra.util import AdHocStruct
from unit.client.mixins.clientmixintest_util import ClientMixinTest
from xpra.client.mixins.stub_client_mixin import StubClientMixin


class StubClientTest(ClientMixinTest):

	def test_mixin(self):
		opts = AdHocStruct()
		self._test_mixin_class(StubClientMixin, opts, {})

	def test_compressed_wrapper(self):
		s = StubClientMixin()
		s.compressed_wrapper("text", "foo", 1)
		for level in (-1, -100):
			try:
				s.compressed_wrapper("text", "bar", level)
			except Exception:
				pass
			else:
				raise Exception("should have failed with invalid level %s" % level)


def main():
	unittest.main()


if __name__ == '__main__':
	main()
