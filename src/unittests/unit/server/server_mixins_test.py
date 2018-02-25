#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2018 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest

from xpra.util import AdHocStruct


class ServerMixinsTest(unittest.TestCase):

	def test_mmap(self):
		from xpra.server.mixins.mmap_server import MMAP_Server
		x = MMAP_Server()
		opts = AdHocStruct()
		opts.mmap = "on"
		x.init(opts)
		assert x.get_info().get("mmap", {}).get("supported") is True

	def test_remotelogging(self):
		from xpra.server.mixins.logging_server import LoggingServer, log
		logfn = log.log
		try:
			messages = []
			def newlogfn(*args):
				messages.append(args)
			log.log = newlogfn
			x = LoggingServer()
			proto = AdHocStruct()
			x._server_sources = {proto : "fake-source"}
			opts = AdHocStruct()
			opts.remote_logging = "on"
			x.init(opts)
			level = 20
			msg = "foo"
			packet = ["logging", level, msg]
			x._process_logging(proto, packet)
			assert len(messages)==1
		finally:
			log.log = logfn

def main():
	unittest.main()


if __name__ == '__main__':
	main()
