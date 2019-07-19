#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2018-2019 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import time
import unittest

from xpra.util import AdHocStruct
from xpra.os_util import get_hex_uuid
from xpra.client.mixins.network_state import NetworkState
from unit.client.mixins.clientmixintest_util import ClientMixinTest


class MixinsTest(ClientMixinTest):

	def test_networkstate(self):
		opts = AdHocStruct()
		opts.pings = True
		opts.bandwidth_limit = 0
		opts.bandwidth_detection = True
		self._test_mixin_class(NetworkState, opts, {"start_time" : time.time()})
		x = self.mixin
		if x.server_start_time<x.start_time:
			raise Exception("invalid time: server=%s vs start=%s" % (x.server_start_time, x.start_time))
		x.uuid = get_hex_uuid()
		x.send_info_request()
		packet = ["info-response", {"foo" : "bar"}]
		self.handle_packet(packet)
		assert x.server_last_info.get("foo")=="bar"

def main():
	unittest.main()


if __name__ == '__main__':
	main()
