#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2018 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest

from xpra.util import AdHocStruct, typedict
from xpra.os_util import monotonic_time
from xpra.client.mixins.network_state import NetworkState
from xpra.client.mixins.mmap import MmapClient
from xpra.client.mixins.remote_logging import RemoteLogging


class MixinsTest(unittest.TestCase):

	def test_networkstate(self):
		x = NetworkState()
		opts = AdHocStruct()
		opts.pings = True
		x.init(opts)
		assert x.get_caps() is not None
		x.server_capabilities = typedict({"start_time" : monotonic_time()})
		x.parse_server_capabilities()
		assert x.server_start_time>=x.start_time, "server_start_time=%s vs start_time=%s" % (x.server_start_time, x.start_time)
		x.send_info_request()
		packet = ["info-response", {"foo" : "bar"}]
		x._process_info_response(packet)
		assert x.server_last_info.get("foo")=="bar"

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

	def test_remotelogging(self):
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
