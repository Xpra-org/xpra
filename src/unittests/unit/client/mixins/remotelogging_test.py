#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2018-2019 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest

from xpra.util import AdHocStruct
from xpra.client.mixins.remote_logging import RemoteLogging
from unit.client.mixins.clientmixintest_util import ClientMixinTest


class MixinsTest(ClientMixinTest):

	def test_remotelogging(self):
		from xpra.log import Logger, is_debug_enabled
		for x in ("network", "crypto", "udp"):
			if is_debug_enabled(x):
				#remote logging will be disabled,
				#so we have to skip this test
				return
		opts = AdHocStruct()
		opts.remote_logging = "yes"
		self._test_mixin_class(RemoteLogging, opts, {
			"remote-logging"	: True,
			})
		assert len(self.packets)==0
		log = Logger("util")
		message = b"hello"
		log.info(message)
		assert len(self.packets)==1
		packet = self.packets[0]
		assert packet[0]=="logging", "expected logging packet but got '%s'" % (packet[0],)
		assert packet[1]==20, "expected INFO level (20) but got %s" % (packet[1],)
		assert packet[2].data==message, "expected message '%s' but got '%s'" % (message, packet[2].data)
		#after cleanup, log messages should not be intercepted:
		self.packets = []
		self.mixin.cleanup()
		log.info("foo")
		assert len(self.packets)==0

def main():
	unittest.main()


if __name__ == '__main__':
	main()
