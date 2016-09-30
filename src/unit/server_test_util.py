#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2016 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import sys
import time
import tempfile
import unittest
import subprocess
from xpra.util import envbool, repr_ellipsized
from xpra.scripts.config import get_defaults
from xpra.platform.dotxpra import DotXpra, osexpand
from xpra.platform.paths import get_socket_dirs

from xpra.log import Logger
log = Logger("test")

HIDE_SUBPROCESS_OUTPUT = envbool("XPRA_HIDE_SUBPROCESS_OUTPUT", True)


class ServerTestUtil(unittest.TestCase):

	@classmethod
	def setUpClass(cls):
		cls.default_config = get_defaults()
		dirs = get_socket_dirs()
		cls.display_start = 100
		cls.dotxpra = DotXpra(dirs[0], dirs)
		cls.default_xpra_args = ["--systemd-run=no", "--pulseaudio=no"]
		ServerTestUtil.existing_displays = cls.dotxpra.displays()
		ServerTestUtil.processes = []
		xpra_list = cls.run_xpra(["list"])
		assert cls.pollwait(xpra_list, 15) is not None

	@classmethod
	def tearDownClass(cls):
		for x in ServerTestUtil.processes:
			try:
				if x.poll() is None:
					x.terminate()
			except:
				log.error("failed to stop subprocess %s", x)
		displays = set(cls.dotxpra.displays())
		new_displays = displays - set(ServerTestUtil.existing_displays)
		if new_displays:
			for x in list(new_displays):
				log("stopping display %s" % x)
				proc = cls.run_xpra(["stop", x])
				proc.communicate(None)


	@classmethod
	def run_env(self):
		return dict((k,v) for k,v in os.environ.items() if k in ("HOME", "HOSTNAME", "SHELL", "TERM", "USER", "USERNAME", "PATH", "PWD", "XAUTHORITY", ))


	@classmethod
	def run_xpra(cls, command, env=None):
		cmd = ["python%i" % sys.version_info[0], "/usr/bin/xpra"] + command + cls.default_xpra_args
		return cls.run_command(cmd, env)

	@classmethod
	def run_command(cls, command, env=None, **kwargs):
		if env is None:
			env = cls.run_env()
		if HIDE_SUBPROCESS_OUTPUT:
			stdout = cls._temp_file()
			stderr = cls._temp_file()
			kwargs = {"stdout" : stdout, "stderr" : stderr}
			log("output of %s sent to %s / %s", command, stdout.name, stderr.name)
		else:
			log("run_command(%s, %s)", command, repr_ellipsized(str(env), 40))
		proc = subprocess.Popen(args=command, env=env, **kwargs)
		ServerTestUtil.processes.append(proc)
		return proc


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
		if os.name=="posix":
			for x in os.listdir("/tmp/.X11-unix"):
				if x.startswith("X"):
					try:
						X11_displays.add(int(x[1:]))
					except:
						pass
		return X11_displays

	@classmethod
	def find_X11_displays(cls):
		return [":%i" % x for x in cls.find_X11_display_numbers()]


	@classmethod
	def find_free_display_no(cls):
		#X11 sockets:
		X11_displays = cls.find_X11_displays()
		displays = cls.dotxpra.displays()
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
			display = cls.find_free_display_no()
		XAUTHORITY = os.environ.get("XAUTHORITY", os.path.expanduser("~/.Xauthority"))
		if len(screens)>1:
			cmd = ["Xvfb", "+extension", "Composite", "-nolisten", "tcp", "-noreset",
					"-auth", XAUTHORITY]
			for i, screen in enumerate(screens):
				(w, h) = screen
				cmd += ["-screen", "%i" % i, "%ix%ix24+32" % (w, h)]
		else:
			import shlex
			cmd = shlex.split(osexpand(cls.default_config.get("xvfb")))
		cmd.append(display)
		return cls.run_command(cmd)


	@classmethod
	def pollwait(cls, proc, timeout=5):
		start = time.time()
		while time.time()-start<timeout:
			v = proc.poll()
			if v is not None:
				return v
			time.sleep(0.1)
		return None

	@classmethod
	def check_start_server(cls, display, *args):
		return cls.check_server("start", display, *args)

	@classmethod
	def check_server(cls, subcommand, display, *args):
		server_proc = cls.run_xpra([subcommand, display, "--no-daemon"]+list(args))
		assert cls.pollwait(server_proc, 3) is None, "server failed to start, returned %s" % server_proc.poll()
		assert display in cls.dotxpra.displays(), "server display not found"
		#query it:
		info = cls.run_xpra(["version", display])
		for _ in range(5):
			r = cls.pollwait(info)
			log("version for %s returned %s", display, r)
			if r is not None:
				assert r==0, "version failed for %s, returned %s" % (display, info.poll())
				break
			time.sleep(1)
		return server_proc

	@classmethod
	def check_stop_server(cls, server_proc, subcommand="stop", display=":99999"):
		stopit = cls.run_xpra([subcommand, display])
		assert cls.pollwait(stopit) is not None, "server failed to exit"
		assert display not in cls.dotxpra.displays(), "server socket for display %s should have been removed" % display
