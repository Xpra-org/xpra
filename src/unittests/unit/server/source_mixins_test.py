#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2018 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest

from xpra.util import typedict, AdHocStruct


class SourceMixinsTest(unittest.TestCase):

	def test_clientinfo(self):
		from xpra.server.source.clientinfo_mixin import ClientInfoMixin
		x = ClientInfoMixin()
		assert x.get_connect_info()
		assert x.get_info()
		c = typedict()
		x.parse_client_caps(c)
		assert x.get_connect_info()
		assert x.get_info()
		x.cleanup()
		assert x.get_connect_info()
		assert x.get_info()

	def test_clientdisplay(self):
		from xpra.server.source.clientdisplay_mixin import ClientDisplayMixin
		x = ClientDisplayMixin()
		assert x.get_info()
		c = typedict()
		x.parse_client_caps(c)
		assert x.get_info()
		x.cleanup()
		assert x.get_info()
		

def main():
	unittest.main()


if __name__ == '__main__':
	main()
