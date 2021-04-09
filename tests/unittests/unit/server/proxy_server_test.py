#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2016-2020 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest
from xpra.os_util import pollwait, WIN32
from unit.server_test_util import ServerTestUtil, log


class ProxyServerTest(ServerTestUtil):

	def test_proxy_start_stop(self):
		display = self.find_free_display()
		log("using free display=%s" % display)
		cmd = ["proxy", display, "--no-daemon"]
		cmdstr = " ".join("'%s'" % c for c in cmd)
		proxy = self.run_xpra(cmd)
		r = pollwait(proxy, 5)
		if r is not None:
			self.show_proc_pipes(proxy)
		assert r is None, "proxy failed to start with cmd=%s, exit code=%s" % (cmdstr, r)
		displays = self.dotxpra.displays()
		assert display in displays, "proxy display '%s' not found in %s" % (display, displays)
		self.check_stop_server(proxy, "stop", display)

	def stop_server(self, server_proc, subcommand, *connect_args):
		if WIN32:
			super().stop_server(server_proc, subcommand, *connect_args)
			return
		log("stop_server%s", (server_proc, subcommand, connect_args))
		if server_proc.poll() is not None:
			return
		server_proc.terminate()
		assert pollwait(server_proc) is not None, "server process %s failed to exit" % server_proc


def main():
	unittest.main()


if __name__ == '__main__':
	main()
