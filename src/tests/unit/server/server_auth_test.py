#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2016 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import unittest
import tempfile
from xpra.exit_codes import EXIT_OK, EXIT_FAILURE, EXIT_PASSWORD_REQUIRED
from tests.unit.server_test_util import ServerTestUtil, log


class ServerAuthTest(ServerTestUtil):

	def _test_auth(self, auth="fail", uri_prefix="", exit_code=0, password=None):
		display = self.find_free_display()
		log("starting test server on %s", display)
		server = self.check_start_server(display, "--auth=%s" % auth)
		#we should always be able to get the version:
		client = self.run_xpra(["xpra", "version", uri_prefix+display])
		assert self.pollwait(client, 5)==0, "version client failed to connect"
		if client.poll() is None:
			client.terminate()
		#try to connect
		cmd = ["xpra", "info", uri_prefix+display]
		f = None
		if password:
			f = tempfile.NamedTemporaryFile(prefix='xprapassword')
			f.file.write(password)
			f.file.flush()
			cmd += ["--password-file=%s" % f.name]
		client = self.run_xpra(cmd)
		r = self.pollwait(client, 5)
		if f:
			f.close()
		assert r==exit_code, "expected info client to return %s but got %s" % (exit_code, client.poll())
		if client.poll() is None:
			client.terminate()
		server.terminate()

	def test_fail(self):
		self._test_auth("fail", "", EXIT_FAILURE)

	def test_reject(self):
		self._test_auth("reject", "", EXIT_PASSWORD_REQUIRED)

	def test_none(self):
		self._test_auth("none", "", EXIT_OK)
		self._test_auth("none", "", EXIT_OK, "foo")

	def test_allow(self):
		self._test_auth("allow", "", EXIT_PASSWORD_REQUIRED)
		self._test_auth("allow", "", EXIT_OK, "foo")



def main():
	if os.name=="posix":
		unittest.main()


if __name__ == '__main__':
	main()
