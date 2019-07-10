#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2018-2019 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest

from xpra.util import AdHocStruct, typedict
from xpra.client.mixins.mmap import MmapClient


class MixinsTest(unittest.TestCase):

	def test_mmap(self):
		x = MmapClient()
		opts = AdHocStruct()
		opts.mmap = "on"
		opts.mmap_group = False
		x.init(opts)
		assert x.get_caps() is not None
		conn = AdHocStruct()
		conn.filename = "/tmp/fake"
		x.setup_connection(conn)
		x.server_capabilities = typedict({
			"mmap.enabled"		: True,
			"mmap.token"		: x.mmap_token,
			"mmap.token_bytes"	: x.mmap_token_bytes,
			"mmap.token_index"	: x.mmap_token_index,
			})
		x.parse_server_capabilities()

def main():
	unittest.main()


if __name__ == '__main__':
	main()
