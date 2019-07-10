#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2018-2019 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import time
import unittest

from xpra.util import AdHocStruct, typedict
from xpra.os_util import get_hex_uuid
from xpra.client.mixins.network_state import NetworkState
from unit.client.mixins.clientmixintest_util import ClientMixinTest


class MixinsTest(ClientMixinTest):

	def test_networkstate(self):
		x = NetworkState()
		fake_protocol = AdHocStruct()
		fake_protocol.get_info = lambda : {}
		x._protocol = fake_protocol
		opts = AdHocStruct()
		opts.pings = True
		opts.bandwidth_limit = 0
		opts.bandwidth_detection = True
		x.init(opts)
		assert x.get_caps() is not None
		x.server_capabilities = typedict({"start_time" : time.time()})
		x.parse_server_capabilities()
		assert x.server_start_time>=x.start_time, "server_start_time=%s vs start_time=%s" % (x.server_start_time, x.start_time)
		x.uuid = get_hex_uuid()
		x.send_info_request()
		packet = ["info-response", {"foo" : "bar"}]
		x._process_info_response(packet)
		assert x.server_last_info.get("foo")=="bar"

def main():
	unittest.main()


if __name__ == '__main__':
	main()
