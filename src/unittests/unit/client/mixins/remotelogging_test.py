#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2018-2019 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest

from xpra.util import AdHocStruct, typedict
from xpra.client.mixins.remote_logging import RemoteLogging


class MixinsTest(unittest.TestCase):

	def test_remotelogging(self):
		from xpra.log import is_debug_enabled
		for x in ("network", "crypto", "udp"):
			if is_debug_enabled(x):
				#remote logging will be disabled,
				#so we have to skip this test
				return
		x = RemoteLogging()
		opts = AdHocStruct()
		opts.remote_logging = "yes"
		x.init(opts)
		assert x.get_caps() is not None
		x.server_capabilities = typedict({
			"remote-logging"	: True,
			})
		x.parse_server_capabilities()
		packets = []
		def send(*args):
			packets.append(args)
		x.send = send
		from xpra.log import Logger
		log = Logger("util")
		message = b"hello"
		log.info(message)
		assert len(packets)==1
		packet = packets[0]
		assert packet[0]=="logging", "expected logging packet but got '%s'" % (packet[0],)
		assert packet[1]==20, "expected INFO level (20) but got %s" % (packet[1],)
		assert packet[2].data==message, "expected message '%s' but got '%s'" % (message, packet[2].data)
		#after cleanup, log messages should not be intercepted:
		x.cleanup()
		log.info("foo")
		assert len(packets)==1

def main():
	unittest.main()


if __name__ == '__main__':
	main()
