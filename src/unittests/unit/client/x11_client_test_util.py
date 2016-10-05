#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2016 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from unit.server_test_util import ServerTestUtil, log

uq = 0

class X11ClientTestUtil(ServerTestUtil):

	def run_client(self, *args):
		client_display = self.find_free_display()
		xvfb = self.start_Xvfb(client_display)
		xvfb.display = client_display
		return xvfb, self.do_run_client(client_display, *args)

	def do_run_client(self, client_display, *args):
		from xpra.scripts.server import xauth_add
		xauth_add(client_display)
		env = self.get_run_env()
		env["DISPLAY"] = client_display
		global uq
		env["XPRA_LOG_PREFIX"] = "client %i: " % uq
		uq +=1 
		log("starting test client on Xvfb %s", client_display)
		return self.run_xpra(["attach"] + list(args) , env)
