#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2016-2018 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import time

from unit.client.x11_client_test_util import X11ClientTestUtil
from xpra.util import envbool
from xpra.os_util import get_hex_uuid, pollwait, which
from xpra.platform.features import CLIPBOARDS
from xpra.log import Logger

log = Logger("clipboard")

SANITY_CHECKS = envbool("XPRA_CLIPBOARD_SANITY_CHECKS", True)

def has_xclip():
	return which("xclip")


class X11ClipboardTestUtil(X11ClientTestUtil):

	def get_clipboard_value(self, display, selection="clipboard"):
		out = self.get_command_output("xclip -d %s -selection %s -o" % (display, selection), shell=True)
		return out.decode()

	def set_clipboard_value(self, display, value, selection="clipboard"):
		cmd = "echo -n '%s' | xclip -d %s -selection %s -i" % (value, display, selection)
		xclip = self.run_command(cmd, shell=True)
		assert pollwait(xclip, 5)==0, "xclip command %s returned %s" % (cmd, xclip.poll())


	def copy_and_verify(self, display1, display2, synced=True, wait=1, selection="clipboard"):
		log("copy_and_verify%s", (display1, display2, synced, wait, selection))
		value = get_hex_uuid()
		self.set_clipboard_value(display1, value)
		#wait for synchronization to occur:
		time.sleep(wait)
		new_value = self.get_clipboard_value(display2)
		if synced:
			assert new_value==value, "clipboard contents do not match, expected '%s' but got '%s'" % (value, new_value)
		else:
			assert new_value!=value, "clipboard contents match but synchronization was not expected: value='%s'" % value
		if SANITY_CHECKS and display2!=display1:
			#verify that the value has not changed on the original display:
			new_value = self.get_clipboard_value(display1)
		return value

	def do_test_copy_selection(self, selection="clipboard", direction="both"):
		log("do_test_copy(%s, %s)", selection, direction)
		server = self.run_server()
		server_display = server.display
		#connect a client:
		xvfb, client = self.run_client(server_display,
									"--clipboard-direction=%s" % direction, "--remote-logging=no")
		assert pollwait(client, 2) is None, "client has exited with return code %s" % client.poll()
		client_display = xvfb.display

		#wait for client to own the clipboard:
		cmd = self.get_xpra_cmd()+["info", server_display]
		for _ in range(10):
			out = self.get_command_output(cmd)
			if out.find(b"clipboard.client=")>0:
				break
			time.sleep(1)

		if SANITY_CHECKS:
			log("sanity checks")
			#xclip sanity check: retrieve from the same display:
			self.copy_and_verify(client_display, client_display, True, wait=0, selection=selection)
			self.copy_and_verify(server_display, server_display, True, wait=0, selection=selection)

		log("copy client %s to server %s", client_display, server_display)
		for _ in range(2):
			self.copy_and_verify(client_display, server_display, direction in ("both", "to-server"), selection=selection)
		log("copy server %s to client %s", server_display, client_display)
		for _ in range(2):
			self.copy_and_verify(server_display, client_display, direction in ("both", "to-client"), selection=selection)
		log("copy client %s to server %s", client_display, server_display)
		for _ in range(2):
			self.copy_and_verify(client_display, server_display, direction in ("both", "to-server"), selection=selection)

		client.terminate()
		xvfb.terminate()
		server.terminate()

	def do_test_copy(self, direction="both"):
		for selection in CLIPBOARDS:
			self.do_test_copy_selection(selection, direction)
