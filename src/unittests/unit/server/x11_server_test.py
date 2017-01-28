#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2016 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import sys
import time
import unittest
from xpra.os_util import pollwait, OSX
from unit.server_test_util import ServerTestUtil, log


class ProxyServerTest(ServerTestUtil):


	def test_display_reuse(self):
		display = self.find_free_display()
		log("starting test server on %s", display)
		server = self.check_start_server(display)
		assert display in self.find_X11_displays()
		#make sure we cannot start another server on the same display:
		try:
			log("should not be able to start another test server on %s", display)
			self.check_start_server(display)
		except:
			pass
		else:
			raise Exception("server using the same display should have failed to start")
		assert server.poll() is None, "server should not have terminated"
		#tell the server to exit and leave the display behind:
		log("asking the server to exit")
		self.check_stop_server(server, "exit", display)
		del server
		assert display not in self.dotxpra.displays(), "server socket for display should have been removed"
		#now we can start it again using "--use-display"
		log("start a new server on the same display")
		server = self.check_start_server(display, "--use-display")
		assert display in self.dotxpra.displays(), "server display not found"
		#shut it down now
		self.check_stop_server(server, "stop", display)
		assert display not in self.find_X11_displays(), "the display %s should have been killed" % display


	def test_existing_Xvfb(self):
		display = self.find_free_display()
		xvfb = self.start_Xvfb(display)
		time.sleep(1)
		assert display in self.find_X11_displays()
		#start server using this display:
		server = self.check_start_server(display, "--use-display")
		self.check_stop_server(server, "stop", display)
		time.sleep(1)
		assert pollwait(xvfb, 2) is None, "the Xvfb should not have been killed by xpra shutting down!"
		xvfb.terminate()


def main():
	if os.name=="posix" and sys.version_info[0]==2 and not OSX:
		unittest.main()


if __name__ == '__main__':
	main()
