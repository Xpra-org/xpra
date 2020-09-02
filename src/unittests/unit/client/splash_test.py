#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2020 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import time
import signal
import unittest
from subprocess import Popen, PIPE

from xpra.util import envbool
from xpra.os_util import pollwait, POSIX, OSX
from unit.process_test_util import ProcessTestUtil, log


USE_DISPLAY = envbool("XPRA_TEST_USE_DISPLAY", False)


class SplashTest(ProcessTestUtil):

	def setUp(self):
		ProcessTestUtil.setUp(self)
		self.splash = None
		self.display = None
		self.xvfb = None
		if not POSIX or OSX:
			return
		if USE_DISPLAY:
			self.display = os.environ.get("DISPLAY", "")
			return
		client_display = self.find_free_display()
		self.xvfb = self.start_Xvfb(client_display)
		self.display = client_display
		try:
			from xpra.x11.bindings.wait_for_x_server import wait_for_x_server
		except ImportError:
			time.sleep(5)
		else:
			wait_for_x_server(client_display.encode(), 10)

	def tearDown(self):
		self.stop_splash()
		self.stop_vfb()

	def stop_vfb(self):
		xvfb = self.xvfb
		if xvfb:
			self.xvfb = None
			xvfb.terminate()

	def stop_splash(self):
		s = self.splash
		if not s:
			return
		try:
			self.do_feed_splash(s, [
			"100:100",
			], 5)
			if pollwait(s, 5) is not None:
				return
			s.terminate()
			if pollwait(s, 5) is not None:
				return
			try:
				s.kill()
			except Exception:
				pass
		finally:
			try:
				s.stdin.close()
			except Exception:
				pass
			self.splash = None

	def _run_splash(self):
		env = self.get_run_env()
		if self.display:
			env["DISPLAY"] = self.display
		cmd = self.get_xpra_cmd()
		cmd += ["splash"]
		log("_run_splash() env=%s, cmd=%s", env, cmd)
		self.splash = Popen(args=cmd, stdin=PIPE, env=env, start_new_session=True)
		return self.splash

	def _feed_splash(self, lines=None, delay=1):
		proc = self._run_splash()
		return self.do_feed_splash(proc, lines, delay)

	def do_feed_splash(self, proc, lines=None, delay=1):
		while lines and proc.poll() is None:
			line = lines.pop(0)
			log("sending '%s'", line)
			proc.stdin.write(line.encode()+b"\n\r")
			proc.stdin.flush()
			if pollwait(proc, delay) is not None:
				break
		return proc

	def test_invalid(self):
		self._feed_splash([
			"notanumber:ignoreit",
			"50:50",
			])
		r = pollwait(self.splash, 5)
		assert r is None, "splash screen should not have terminated"
		#try killing it with a signal:
		self.splash.send_signal(signal.SIGTERM)
		r = pollwait(self.splash, 5)
		assert r is not None, "expected splash to exit"

	def test_full(self):
		self._feed_splash([
			"10:10",
			"100:100",
			])
		r = pollwait(self.splash, 5)
		assert r is not None, "splash screen should have terminated"
		assert r==0, "exit code should be zero, but got %s" % r
		self.stop_splash()

	def test_partial(self):
		self._feed_splash([
			"10:10",
			"20:20",
			"90:90",
			])
		assert self.splash.poll() is None, "splash screen should still be running"
		self.stop_splash()


def main():
	unittest.main()


if __name__ == '__main__':
	main()
