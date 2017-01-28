#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2016-2017 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import sys
import time
import tempfile
import unittest
import subprocess
from xpra.util import envbool, envint, repr_ellipsized
from xpra.os_util import OSEnvContext, pollwait
from xpra.scripts.config import get_defaults
from xpra.platform.dotxpra import DotXpra, osexpand
from xpra.platform.paths import get_xpra_command

from xpra.log import Logger
log = Logger("test")

XPRA_TEST_DEBUG = envbool("XPRA_TEST_DEBUG", False)
SERVER_TIMEOUT = envint("XPRA_TEST_SERVER_TIMEOUT", 8)
XVFB_TIMEOUT = envint("XPRA_TEST_XVFB_TIMEOUT", 5)


class ServerTestUtil(unittest.TestCase):

	@classmethod
	def displays(cls):
		if os.name!="posix":
			return []
		return cls.dotxpra.displays()

	@classmethod
	def setUpClass(cls):
		from xpra.scripts.server import find_log_dir
		os.environ["XPRA_LOG_DIR"] = find_log_dir()
		cls.default_config = get_defaults()
		cls.display_start = 100
		cls.dotxpra = DotXpra("/tmp", ["/tmp"])
		cls.default_xpra_args = ["--systemd-run=no", "--pulseaudio=no", "--socket-dirs=/tmp", "--speaker=no", "--microphone=no"]
		ServerTestUtil.existing_displays = cls.displays()
		ServerTestUtil.processes = []
		xpra_list = cls.run_xpra(["list"])
		assert pollwait(xpra_list, 15) is not None, "xpra list returned %s" % xpra_list.poll()

	@classmethod
	def tearDownClass(cls):
		for x in ServerTestUtil.processes:
			try:
				if x.poll() is None:
					x.terminate()
			except:
				log.error("failed to stop subprocess %s", x)
		displays = set(cls.displays())
		new_displays = displays - set(ServerTestUtil.existing_displays)
		if new_displays:
			for x in list(new_displays):
				log("stopping display %s" % x)
				proc = cls.run_xpra(["stop", x])
				proc.communicate(None)


	@classmethod
	def get_run_env(self):
		return dict((k,v) for k,v in os.environ.items() if
				k.startswith("XPRA") or k in ("HOME", "HOSTNAME", "SHELL", "TERM", "USER", "USERNAME", "PATH", "PWD", "XAUTHORITY", "PYTHONPATH", ))


	@classmethod
	def run_xpra(cls, command, env=None):
		xpra_cmd = get_xpra_command()
		cmd = ["python%i" % sys.version_info[0]] + xpra_cmd + command + cls.default_xpra_args
		return cls.run_command(cmd, env)

	@classmethod
	def run_command(cls, command, env=None, **kwargs):
		if env is None:
			env = cls.get_run_env()
			env["XPRA_FLATTEN_INFO"] = "0"
		if XPRA_TEST_DEBUG:
			log("run_command(%s, %s)", command, repr_ellipsized(str(env), 40))
		else:
			if "stdout" not in kwargs:
				stdout = cls._temp_file()
				kwargs["stdout"] = stdout
				log("stdout of %s sent to %s", command, stdout.name)
			if "stderr" not in kwargs:
				stderr = cls._temp_file()
				kwargs["stderr"] = stderr
				log("stderr of %s sent to %s", command, stderr.name)
		try:
			proc = subprocess.Popen(args=command, env=env, **kwargs)
		except OSError as e:
			log.warn("run_command(%s, %s, %s) %s", command, env, kwargs, e)
			raise
		ServerTestUtil.processes.append(proc)
		return proc


	@classmethod
	def get_command_output(cls, command, env=None, **kwargs):
		proc = cls.run_command(command, env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, **kwargs)
		out,_ = proc.communicate()
		return out


	@classmethod
	def _temp_file(self, data=None):
		f = tempfile.NamedTemporaryFile(prefix='xpraserverpassword')
		if data:
			f.file.write(data)
		f.file.flush()
		return f


	@classmethod
	def find_X11_display_numbers(cls):
		#use X11 sockets:
		X11_displays = set()
		if os.name=="posix" and os.path.exists("/tmp/.X11-unix"):
			for x in os.listdir("/tmp/.X11-unix"):
				if x.startswith("X"):
					try:
						X11_displays.add(int(x[1:]))
					except:
						pass
		return X11_displays

	@classmethod
	def find_X11_displays(cls):
		if os.name!="posix":
			return []
		return [":%i" % x for x in cls.find_X11_display_numbers()]


	@classmethod
	def find_free_display_no(cls):
		#X11 sockets:
		X11_displays = cls.find_X11_displays()
		displays = cls.displays()
		start = cls.display_start % 10000
		for i in range(start, 20000):
			display = ":%i" % i
			if display not in displays and display not in X11_displays:
				cls.display_start += 100
				return i
		raise Exception("failed to find any free displays!")

	@classmethod
	def find_free_display(cls):
		return ":%i" % cls.find_free_display_no()


	@classmethod
	def start_Xvfb(cls, display=None, screens=[(1024,768)]):
		assert os.name=="posix"
		if display is None:
			display = cls.find_free_display()
		with OSEnvContext():
			XAUTHORITY = os.environ.get("XAUTHORITY", os.path.expanduser("~/.Xauthority"))
			for x in list(os.environ.keys()):
				if x in ("LOGNAME", "USER", "PATH", "LANG", "TERM", "HOME", "USERNAME", "PYTHONPATH", "HOSTNAME"):	#DBUS_SESSION_BUS_ADDRESS
					#keep it
					continue
				try:
					del os.environ[x]
				except:
					pass
			if len(screens)>1:
				cmd = ["Xvfb", "+extension", "Composite", "-nolisten", "tcp", "-noreset",
						"-auth", XAUTHORITY]
				for i, screen in enumerate(screens):
					(w, h) = screen
					cmd += ["-screen", "%i" % i, "%ix%ix24+32" % (w, h)]
			else:
				xvfb_cmd = cls.default_config.get("xvfb")
				assert xvfb_cmd, "no 'xvfb' command in default config"
				import shlex
				cmd = shlex.split(osexpand(xvfb_cmd))
				try:
					i = cmd.index("/etc/xpra/xorg.conf")
				except ValueError:
					i = -1
				if i>0 and os.path.exists("./etc/xpra/xorg.conf"):
					cmd[i] = "./etc/xpra/xorg.conf"
			cmd.append(display)
			os.environ["DISPLAY"] = display
			os.environ["XPRA_LOG_DIR"] = "/tmp"
			cmd_expanded = [osexpand(v) for v in cmd]
			cmdstr = " ".join("'%s'" % x for x in cmd_expanded)
			xvfb = cls.run_command(cmd_expanded, stdout=sys.stdout, stderr=sys.stderr)
			time.sleep(1)
			print("xvfb(%s)=%s" % (cmdstr, xvfb))
			assert pollwait(xvfb, XVFB_TIMEOUT) is None, "xvfb command \"%s\" failed and returned %s" % (cmdstr, xvfb.poll())
			return xvfb


	@classmethod
	def run_server(cls, *args):
		display = cls.find_free_display()
		server = cls.check_server("start", display, *args)
		server.display = display
		return server

	@classmethod
	def check_start_server(cls, display, *args):
		return cls.check_server("start", display, *args)

	@classmethod
	def check_server(cls, subcommand, display, *args):
		cmd = [subcommand, display, "--no-daemon"]+list(args)
		server_proc = cls.run_xpra(cmd)
		assert pollwait(server_proc, SERVER_TIMEOUT) is None, "server failed to start with '%s', returned %s" % (cmd, server_proc.poll())
		live = cls.dotxpra.displays()
		assert display in live, "server display '%s' not found in live displays %s" % (display, live)
		#query it:
		info = cls.run_xpra(["version", display])
		for _ in range(5):
			r = pollwait(info)
			log("version for %s returned %s", display, r)
			if r is not None:
				assert r==0, "version failed for %s, returned %s" % (display, info.poll())
				break
			time.sleep(1)
		return server_proc

	@classmethod
	def check_stop_server(cls, server_proc, subcommand="stop", display=":99999"):
		stopit = cls.run_xpra([subcommand, display])
		assert pollwait(stopit) is not None, "server failed to exit"
		assert display not in cls.dotxpra.displays(), "server socket for display %s should have been removed" % display
