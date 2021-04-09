#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2016-2020 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import time
import uuid
import unittest

from xpra.util import envint
from xpra.exit_codes import EXIT_STR
from xpra.os_util import load_binary_file, pollwait, OSX, POSIX
from xpra.platform.paths import get_download_dir
from unit.client.x11_client_test_util import X11ClientTestUtil, log

CLIENT_TIMEOUT = envint("XPRA_TEST_CLIENT_TIMEOUT", 20)


class X11ClientTest(X11ClientTestUtil):

	def do_test_connect(self, disconnect=True, client_args=(), server_args=()):
		display = self.find_free_display()
		log("starting test server on %s", display)
		server_args = ["--start=xterm"] + list(server_args)
		server = self.check_start_server(display, *server_args)
		xvfb1, client1 = self.run_client(display, *client_args)
		r = pollwait(client1, CLIENT_TIMEOUT)
		assert r is None, "client1 exited with code %s" % EXIT_STR.get(r, r)
		xvfb2, client2 = self.run_client(display, *client_args)
		r = pollwait(client2, CLIENT_TIMEOUT)
		assert r is None, "client2 exited with code %s" % EXIT_STR.get(r, r)
		if disconnect:
			#starting a second client should disconnect the first when not sharing
			assert pollwait(client1, 2) is not None, "the first client should have been disconnected"
		#killing the Xvfb should kill the client
		xvfb1.terminate()
		xvfb2.terminate()
		assert pollwait(xvfb1, CLIENT_TIMEOUT) is not None
		assert pollwait(xvfb2, CLIENT_TIMEOUT) is not None
		assert pollwait(client1, CLIENT_TIMEOUT) is not None
		assert pollwait(client2, CLIENT_TIMEOUT) is not None
		server.terminate()


	def test_connect(self):
		self.do_test_connect()

	def test_sharing(self):
		self.do_test_connect(False, server_args=("--sharing=yes",))

	def test_opengl(self):
		self.do_test_connect(client_args=("--opengl=yes",))

	def test_multiscreen(self):
		client_display = self.find_free_display()
		xvfb = self.start_Xvfb(client_display, screens=[(1024,768), (1200, 1024)])
		#multiscreen requires Xvfb, which may not support opengl:
		self.do_run_client(client_display, "--opengl=no").terminate()
		xvfb.terminate()

	def test_nocomposite(self):
		client_display = self.find_free_display()
		self.start_Xvfb(client_display, extensions=("-Composite"))
		self.do_run_client(client_display).terminate()


	def _test_client_depth(self, server_display):
		#start vfb with display-depth:
		for client_display_depth in (16, 24, 30):
			client_display = self.find_free_display()
			xvfb = self.start_Xvfb(client_display, depth=client_display_depth)
			try:
				for client_depth in (16, 24, 30):
					client = self.do_run_client(client_display, server_display,
											"--pixel-depth=%i" % client_depth)
					r = pollwait(client, 5)
					assert r is None, "client has terminated with exit code %i" % r
					client.terminate()
			finally:
				xvfb.terminate()

	def test_depth(self):
		for server_depth in (16, 24, 30):
			server_display = self.find_free_display()
			log("depth=%i starting test server on %s", server_depth, server_display)
			server = self.check_start_server(server_display,
											"--start=xterm", "--sync-xvfb=50",
											"--pixel-depth=%i" % server_depth)
			self._test_client_depth(server_display)
			server.terminate()

	def do_test_control_send_file(self, data):
		f = self._temp_file(data)
		try:
			display = self.find_free_display()
			server = self.check_start_server(display)
			xvfb, client = self.run_client(display, "--file-transfer=yes")
			assert pollwait(client, CLIENT_TIMEOUT) is None
			#send a file to this client:
			send_file_command = ["control", display, "send-file", f.name, "0", "*"]
			send_file = self.run_xpra(send_file_command)
			assert pollwait(send_file, CLIENT_TIMEOUT)==0, "send-file command returncode is %s" % send_file.poll()
			time.sleep(1)
			#now verify the file can be found in the download directory
			filename = os.path.join(os.path.expanduser(get_download_dir()), os.path.basename(f.name))
			assert os.path.exists(filename), "cannot find %s" % filename
			readback = load_binary_file(filename)
			assert readback==data, "file data corrupted"
			os.unlink(filename)
			#cleanup:
			client.terminate()
			xvfb.terminate()
			server.terminate()
		finally:
			f.close()

	def test_control_send_file(self):
		data = b"".join(uuid.uuid4().bytes for _ in range(100))
		self.do_test_control_send_file(data)


def main():
	if POSIX and not OSX:
		unittest.main()


if __name__ == '__main__':
	main()
