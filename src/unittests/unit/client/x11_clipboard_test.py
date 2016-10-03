#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2016 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import sys
import time
import unittest
from xpra.os_util import get_hex_uuid
from unit.client.x11_client_test_util import X11ClientTestUtil


class X11ClipboardTest(X11ClientTestUtil):

	@classmethod
	def setUpClass(cls):
		super(X11ClipboardTest, cls).setUpClass()
		X11ClipboardTest.default_xpra_args += ["-d clipboard"]


	def copy_and_verify(self, display1, display2, synced=True):
		value = get_hex_uuid()
		xclip = self.run_command("echo '%s' | xclip -selection clipboard -i -d %s" % (value, display1), shell=True)
		assert self.pollwait(xclip, 5)==0, "xclip returned %s" % xclip.poll()
		#wait for synchronization to occur:
		time.sleep(1)
		import subprocess
		xclip = self.run_command("xclip -selection clipboard -o -d %s" % (display2), shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
		out,_ = xclip.communicate()
		new_value = out.strip("\n")
		if synced:
			assert new_value==value, "clipboard contents do not match, expected '%s' but got '%s'" % (value, new_value)
		else:
			assert new_value!=value, "clipboard contents match but synchronization was not expected: value='%s'" % value
		return value

	def do_test_copy(self, direction="both"):
		server = self.run_server()
		server_display = server.display
		#connect a client:
		xvfb, client = self.run_client(server_display, "--clipboard-direction=%s" % direction)
		assert self.pollwait(client, 2) is None, "client has exited with return code %s" % client.poll()
		client_display = xvfb.display

		for _ in range(2):
			self.copy_and_verify(client_display, server_display, direction in ("both", "client-to-server"))
		for _ in range(2):
			self.copy_and_verify(server_display, client_display, direction in ("both", "server-to-client"))
		for _ in range(2):
			self.copy_and_verify(client_display, server_display, direction in ("both", "client-to-server"))

		client.terminate()
		xvfb.terminate()
		server.terminate()

	def Xtest_copy(self):
		self.do_test_copy()

	def Xtest_disabled(self):
		self.do_test_copy("disabled")


def main():
	if os.name=="posix" and sys.version_info[0]==2:
		unittest.main()


if __name__ == '__main__':
	main()
