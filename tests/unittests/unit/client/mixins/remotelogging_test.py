#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2018-2020 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest

from xpra.util import AdHocStruct
from xpra.client.mixins import remote_logging
from unit.test_util import silence_info
from unit.client.mixins.clientmixintest_util import ClientMixinTest


class MixinsTest(ClientMixinTest):

	def test_remotelogging(self):
		from xpra.log import Logger, is_debug_enabled
		for x in ("network", "crypto"):
			if is_debug_enabled(x):
				#remote logging will be disabled,
				#so we have to skip this test
				return
		opts = AdHocStruct()
		opts.remote_logging = "yes"
		with silence_info(remote_logging):
			self._test_mixin_class(remote_logging.RemoteLogging, opts, {
				"remote-logging"	: True,
				})
		assert len(self.packets)==0
		logger = Logger("util")
		message = b"hello"
		logger.info(message)
		assert len(self.packets)==1
		packet = self.packets[0]
		assert packet[0]=="logging", "expected logging packet but got '%s'" % (packet[0],)
		assert packet[1]==20, "expected INFO level (20) but got %s" % (packet[1],)
		#data might be using a compressed wrapper:
		data = getattr(packet[2], "data", packet[2])
		assert data==message, "expected message '%s' but got '%s'" % (message, data)
		#after cleanup, log messages should not be intercepted:
		self.packets = []
		self.mixin.cleanup()
		with silence_info(remote_logging):
			logger.info("foo")
		assert len(self.packets)==0

def main():
	unittest.main()


if __name__ == '__main__':
	main()
