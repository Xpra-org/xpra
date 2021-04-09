#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2016-2020 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import time
import unittest

from xpra.util import typedict
from xpra.os_util import pollwait, which, OSX, POSIX
from unit.server_test_util import ServerTestUtil, log


class X11ServerTest(ServerTestUtil):

	def start_test_xvfb_and_server(self, *args):
		display = self.find_free_display()
		xvfb = self.start_Xvfb(display)
		time.sleep(1)
		assert display in self.find_X11_displays()
		#start server using this display:
		server = self.check_start_server(display, "--use-display=yes", *args)
		return display, xvfb, server

	def start_test_server(self, *args):
		display = self.find_free_display()
		log("starting test server on %s", display)
		server = self.check_start_server(display, *args)
		assert display in self.find_X11_displays()
		return display, server


	def test_display_reuse(self):
		display, server = self.start_test_server()
		#make sure we cannot start another server on the same display:
		saved_spe = self.show_proc_error
		def raise_exception_no_log(*args):
			raise Exception("%s" % args)
		#suspend process error logging:
		self.show_proc_error = raise_exception_no_log
		try:
			try:
				log("should not be able to start another test server on %s", display)
				self.check_start_server(display)
			except Exception:
				pass
			else:
				raise Exception("server using the same display should have failed to start")
		finally:
			self.show_proc_error = saved_spe
		assert server.poll() is None, "server should not have terminated"
		#tell the server to exit and leave the display behind:
		log("asking the server to exit")
		self.check_stop_server(server, "exit", display)
		del server
		assert display not in self.dotxpra.displays(), "server socket for display should have been removed"
		#now we can start it again using "--use-display"
		log("start a new server on the same display")
		server = self.check_start_server(display, "--use-display=yes")
		assert display in self.dotxpra.displays(), "server display not found"
		#shut it down now
		self.check_stop_server(server, "stop", display)
		assert display not in self.find_X11_displays(), "the display %s should have been killed" % display


	def test_existing_Xvfb(self):
		display, xvfb, server = self.start_test_xvfb_and_server()
		self.check_stop_server(server, "stop", display)
		time.sleep(1)
		assert pollwait(xvfb, 2) is None, "the Xvfb should not have been killed by xpra shutting down!"
		xvfb.terminate()


	def test_dbus(self):
		dbus_send = which("dbus-send")
		if not dbus_send:
			print("Warning: dbus test skipped, 'dbus-send' not found")
			return
		#make sure this is recorded,
		#so kill the xvfb *after* we exit
		display, xvfb, server = self.start_test_xvfb_and_server("--start=xterm", "--start=xterm", "-d", "dbus")	#2 windows
		info = self.get_server_info(display)
		assert info
		tinfo = typedict(info)
		dstr = display.lstrip(":")
		env = self.get_run_env()
		env["DISPLAY"] = display
		#use the dbus environment from the server:
		for k,v in tinfo.items():
			if k.startswith("env.DBUS_"):
				env[k[4:]] = v
		#unchecked calls:
		for args in (
			("org.xpra.Server.Focus", "int32:1"),
			#("org.xpra.Server.Suspend", ),		#hangs?
			("org.xpra.Server.Resume", ),
			("org.xpra.Server.Ungrab", ),
			("org.xpra.Server.Start", "string:xterm"),
			("org.xpra.Server.StartChild", "string:xterm"),
			("org.xpra.Server.EnableDebug", "string:keyboard"),
			("org.xpra.Server.KeyPress", "int32:36"),		#Return key with default layout?
			("org.xpra.Server.KeyRelease", "int32:36"),		#Return key
			("org.xpra.Server.ClearKeysPressed", ),
			("org.xpra.Server.SetKeyboardRepeat", "int32:200", "int32:50"),
			("org.xpra.Server.DisableDebug", "string:keyboard"),
			("org.xpra.Server.ListClients", ),
			("org.xpra.Server.DetachClient", "string:nomatch"),
			("org.xpra.Server.DetachAllClients", ),
			("org.xpra.Server.GetAllInfo", ),
			("org.xpra.Server.GetInfo", "string:keyboard"),
			("org.xpra.Server.ListWindows", ),
			("org.xpra.Server.LockBatchDelay", "int32:1", "int32:10"),
			("org.xpra.Server.UnlockBatchDelay", "int32:1"),
			("org.xpra.Server.MovePointer", "int32:1", "int32:100", "int32:100"),
			("org.xpra.Server.MouseClick", "int32:1", "boolean:true"),
			("org.xpra.Server.MouseClick", "int32:1", "boolean:false"),
			("org.xpra.Server.MoveWindowToWorkspace", "int32:1", "int32:2"),
			("org.xpra.Server.RefreshAllWindows", ),
			("org.xpra.Server.RefreshWindow", "int32:1"),
			("org.xpra.Server.RefreshWindows", "array:int32:1:2:3"),
			("org.xpra.Server.ResetVideoRegion", "int32:1"),
			("org.xpra.Server.ResetWindowFilters", ),
			("org.xpra.Server.ResetXSettings", ),
			("org.xpra.Server.SendNotification", "int32:1", "string:title", "string:message", "string:*"),
			("org.xpra.Server.CloseNotification", "int32:1", "string:*"),
			("org.xpra.Server.SendUIClientCommand", "array:string:test"),
			("org.xpra.Server.SetClipboardProperties", "string:direction", "int32:1000", "int32:1000"),
			("org.xpra.Server.SetIdleTimeout", "int32:100"),
			("org.xpra.Server.SetLock", "string:true"),
			("org.xpra.Server.SetLock", "string:false"),
			("org.xpra.Server.SetLock", "string:auto"),
			("org.xpra.Server.SetSharing", "string:no"),
			("org.xpra.Server.SetScreenSize", "int32:1024", "int32:768"),
			("org.xpra.Server.SetUIDriver", "string:invalid"),
			("org.xpra.Server.SetVideoRegion", "int32:1", "int32:10", "int32:10", "int32:100", "int32:100"),
			("org.xpra.Server.SetVideoRegionDetection", "int32:1", "boolean:true"),
			("org.xpra.Server.SetVideoRegionDetection", "int32:1", "boolean:false"),
			("org.xpra.Server.SetVideoRegionEnabled", "int32:1", "boolean:true"),
			("org.xpra.Server.SetVideoRegionEnabled", "int32:1", "boolean:false"),
			#("org.xpra.Server.SetVideoRegionExclusionZones", ...
			("org.xpra.Server.SetWindowEncoding", "int32:1", "string:png"),
			("org.xpra.Server.SetWindowScaling", "int32:1", "string:200%"),
			("org.xpra.Server.SetWindowScalingControl", "int32:1", "string:auto"),
			("org.xpra.Server.SetWindowScalingControl", "int32:1", "string:50"),
			("org.xpra.Server.SetWorkarea", "int32:10", "int32:10", "int32:1000", "int32:740"),
			("org.xpra.Server.ShowAllWindows", ),
			("org.xpra.Server.SyncXvfb", ),
			("org.xpra.Server.SetDPI", "int32:144", "int32:144"),
			("org.xpra.Server.ToggleFeature", "string:bell", "string:off"),
			#generic dbus server queries:
			("org.xpra.Server.Get", "string:session_name"),
			("org.xpra.Server.GetAll", ),
			("org.xpra.Server.Set", "string:session_name", "string:foo"),
			):
			cmd = [dbus_send, "--session", "--type=method_call",
					"--dest=org.xpra.Server%s" % dstr, "/org/xpra/Server"] + list(args)
			proc = self.run_command(cmd, env=env)
			assert pollwait(proc, 20) is not None, "dbus-send is taking too long: %s" % (cmd,)
		#properties using interface org.freedesktop.DBus.Properties:
		for args in (
			("Get", "string:idle-timeout"),
			("Get", "string:does-not-exist"),
			("GetAll", ),
			("Set", "string:idle-timeout", "int32:20"),
			("Set", "string:does-not-exist", "string:irrelevant"),
			):
			cmd = [dbus_send, "--session", "--type=method_call", "--print-reply",
					"--dest=org.xpra.Server%s" % dstr, "/org/xpra/Server",
					"org.freedesktop.DBus.Properties.%s" % args[0], "string:org.xpra.Server%s" % dstr
					] + list(args[1:])
			proc = self.run_command(cmd, env=env)
			assert pollwait(proc, 20) is not None, "dbus-send is taking too long: %s" % (cmd,)

		self.check_stop_server(server, "exit", display)
		xvfb.terminate()


def main():
	if POSIX and not OSX:
		unittest.main()


if __name__ == '__main__':
	main()
