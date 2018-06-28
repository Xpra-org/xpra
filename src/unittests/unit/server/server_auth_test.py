#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2016-2017 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import unittest
from xpra.os_util import pollwait, OSX, POSIX, PYTHON2
from xpra.exit_codes import EXIT_OK, EXIT_FAILURE, EXIT_PASSWORD_REQUIRED
from unit.server_test_util import ServerTestUtil, log


class ServerAuthTest(ServerTestUtil):

	def _test_auth(self, auth="fail", uri_prefix="", exit_code=0, password=None):
		display = self.find_free_display()
		log("starting test server on %s", display)
		server = self.check_start_server(display, "--auth=%s" % auth, "--printing=no")
		#we should always be able to get the version:
		client = self.run_xpra(["version", uri_prefix+display])
		assert pollwait(client, 5)==0, "version client failed to connect"
		if client.poll() is None:
			client.terminate()
		#try to connect
		cmd = ["info", uri_prefix+display]
		f = None
		if password:
			f = self._temp_file(password)
			cmd += ["--password-file=%s" % f.name]
		client = self.run_xpra(cmd)
		r = pollwait(client, 5)
		if f:
			f.close()
		if client.poll() is None:
			client.terminate()
		server.terminate()
		assert r==exit_code, "expected info client to return %s but got %s" % (exit_code, r)

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

	def test_file(self):
		from xpra.os_util import get_hex_uuid
		password = get_hex_uuid()
		f = self._temp_file(password)
		self._test_auth("file", "", EXIT_PASSWORD_REQUIRED)
		self._test_auth("file:filename=%s" % f.name, "", EXIT_PASSWORD_REQUIRED)
		self._test_auth("file:filename=%s" % f.name, "", EXIT_OK, password)
		self._test_auth("file:filename=%s" % f.name, "", EXIT_FAILURE, password+"A")
		f.close()

	def test_multifile(self):
		from xpra.platform.info import get_username
		username = get_username()
		from xpra.os_util import get_hex_uuid
		password = get_hex_uuid()
		displays = ""
		data = "%s|%s|%i|%i|%s||" % (username, password, os.getuid(), os.getgid(), displays)
		f = self._temp_file(data)
		self._test_auth("multifile", "", EXIT_PASSWORD_REQUIRED)
		self._test_auth("multifile:filename=%s" % f.name, "", EXIT_PASSWORD_REQUIRED)
		self._test_auth("multifile:filename=%s" % f.name, "", EXIT_OK, password)
		self._test_auth("multifile:filename=%s" % f.name, "", EXIT_FAILURE, password+"A")
		f.close()


def main():
	if POSIX and PYTHON2 and not OSX:
		unittest.main()


if __name__ == '__main__':
	main()
