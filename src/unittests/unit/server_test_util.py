#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2016-2018 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import sys
import time
import tempfile
import unittest
import subprocess
from xpra.util import envbool, envint, repr_ellipsized
from xpra.os_util import pollwait, osexpand, bytestostr, POSIX, WIN32
from xpra.scripts.config import get_defaults
from xpra.platform.dotxpra import DotXpra
from xpra.platform.paths import get_xpra_command

from xpra.log import Logger
log = Logger("test")

XPRA_TEST_DEBUG = envbool("XPRA_TEST_DEBUG", False)
SERVER_TIMEOUT = envint("XPRA_TEST_SERVER_TIMEOUT", 8)
XVFB_TIMEOUT = envint("XPRA_TEST_XVFB_TIMEOUT", 8)
STOP_WAIT_TIMEOUT = envint("XPRA_STOP_WAIT_TIMEOUT", 10)
DELETE_TEMP_FILES = envbool("XPRA_DELETE_TEMP_FILES", True)
SHOW_XORG_OUTPUT = envbool("XPRA_SHOW_XORG_OUTPUT", False)


class ServerTestUtil(unittest.TestCase):

	@classmethod
	def displays(cls):
		if not POSIX:
			return []
		return cls.dotxpra.displays()

	@classmethod
	def setUpClass(cls):
		from xpra.server.server_util import find_log_dir
		os.environ["XAUTHORITY"] = os.path.expanduser("~/.Xauthority")
		os.environ["XPRA_LOG_DIR"] = find_log_dir()
		os.environ["XPRA_NOTTY"] = "1"
		os.environ["XPRA_FLATTEN_INFO"] = "0"
		os.environ["XPRA_NOTTY"] = "1"
		cls.default_env = os.environ.copy()
		cls.default_config = get_defaults()
		cls.display_start = 100+sys.version_info[0]
		cls.dotxpra = DotXpra("/tmp", ["/tmp"])
		cls.default_xpra_args = ["--speaker=no", "--microphone=no"]
		if not WIN32:
			cls.default_xpra_args += ["--systemd-run=no", "--pulseaudio=no", "--socket-dirs=/tmp"]
		cls.existing_displays = cls.displays()
		cls.processes = []

	@classmethod
	def tearDownClass(cls):
		for x in cls.processes:
			try:
				if x.poll() is None:
					x.terminate()
			except:
				log.error("failed to stop subprocess %s", x)
		displays = set(cls.displays())
		new_displays = displays - set(cls.existing_displays)
		if new_displays:
			for x in list(new_displays):
				log("stopping display %s" % x)
				try:
					cmd = cls.get_xpra_cmd()+["stop", x]
					proc = subprocess.Popen(cmd)
					proc.communicate(None)
				except Exception:
					log.error("failed to cleanup display '%s'", x, exc_info=True)

	def setUp(self):
		os.environ.clear()
		os.environ.update(self.default_env)
		self.temp_files = []
		xpra_list = self.run_xpra(["list"])
		assert pollwait(xpra_list, 15) is not None, "xpra list returned %s" % xpra_list.poll()

	def tearDown(self):
		if DELETE_TEMP_FILES:
			for x in self.temp_files:
				try:
					os.unlink(x)
				except:
					pass


	@classmethod
	def get_run_env(self):
		env = dict((k,v) for k,v in os.environ.items() if
				k.startswith("XPRA") or k in ("HOME", "HOSTNAME", "SHELL", "TERM", "USER", "USERNAME", "PATH", "XAUTHORITY", "PWD", "PYTHONPATH", ))
		return env

	@classmethod
	def which(cls, cmd):
		try:
			from xpra.os_util import get_status_output, strtobytes
			code, out, _ = get_status_output(["which", cmd])
			if code==0:
				return strtobytes(out.splitlines()[0])
		except:
			pass
		return cmd

	def run_xpra(self, xpra_args, env=None, **kwargs):
		cmd = self.get_xpra_cmd()+list(xpra_args)
		return self.run_command(cmd, env, **kwargs)

	@classmethod
	def get_xpra_cmd(cls):
		xpra_cmd = get_xpra_command()
		if xpra_cmd==["xpra"]:
			xpra_cmd = [cls.which("xpra")]
		cmd = xpra_cmd + cls.default_xpra_args
		pyexename = "python%i" % sys.version_info[0]
		exe = bytestostr(xpra_cmd[0])
		if exe.endswith(pyexename):
			pass
		elif WIN32 and exe.endswith("%s.exe" % pyexename):
			pass
		else:
			cmd = [pyexename] + xpra_cmd + cls.default_xpra_args
		return cmd

	def run_command(self, command, env=None, **kwargs):
		if env is None:
			env = self.get_run_env()
		if env is not None and not WIN32:
			kwargs["env"] = env
		stdout_file = stderr_file = None
		if isinstance(command, str):
			strcommand = command
		else:
			strcommand = " ".join("'%s'" % x for x in command)
		if XPRA_TEST_DEBUG:
			log("************************")
			log("run_command(%s, %s)", " ".join('"%s"' % x for x in command), repr_ellipsized(str(env), 40))
			log("************************")
		else:
			if "stdout" not in kwargs:
				stdout_file = self._temp_file(prefix="xpra-stdout-")
				kwargs["stdout"] = stdout_file
				log("stdout: %s for %s", stdout_file.name, strcommand)
			if "stderr" not in kwargs:
				stderr_file = self._temp_file(prefix="xpra-stderr-")
				kwargs["stderr"] = stderr_file
				log("stderr: %s for %s", stderr_file.name, strcommand)
		try:
			proc = subprocess.Popen(args=command, **kwargs)
			proc.stdout_file = stdout_file
			proc.stderr_file = stderr_file
		except OSError as e:
			log.warn("run_command(%s, %s, %s) %s", command, env, kwargs, e)
			raise
		self.processes.append(proc)
		return proc


	def get_command_output(self, command, env=None, **kwargs):
		proc = self.run_command(command, env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, **kwargs)
		out,_ = proc.communicate()
		return out


	def _temp_file(self, data=None, prefix="xpra-"):
		f = tempfile.NamedTemporaryFile(prefix=prefix, delete=DELETE_TEMP_FILES)
		if data:
			f.file.write(data)
		f.file.flush()
		self.temp_files.append(f.name)
		return f


	@classmethod
	def find_X11_display_numbers(cls):
		#use X11 sockets:
		X11_displays = set()
		if POSIX and os.path.exists("/tmp/.X11-unix"):
			for x in os.listdir("/tmp/.X11-unix"):
				if x.startswith("X"):
					try:
						X11_displays.add(int(x[1:]))
					except:
						pass
		return X11_displays

	@classmethod
	def find_X11_displays(cls):
		if not POSIX:
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


	def start_Xvfb(self, display=None, screens=[(1024,768)]):
		assert POSIX
		if display is None:
			display = self.find_free_display()
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
					"-auth", self.default_env["XAUTHORITY"]]
			for i, screen in enumerate(screens):
				(w, h) = screen
				cmd += ["-screen", "%i" % i, "%ix%ix24+32" % (w, h)]
		else:
			xvfb_cmd = self.default_config.get("xvfb")
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
		if SHOW_XORG_OUTPUT:
			stdout = sys.stdout
			stderr = sys.stderr
		else:
			stdout = self._temp_file(prefix="Xorg-stdout-")
			log("stdout=%s for %s", stdout.name, cmd)
			stderr = self._temp_file(prefix="Xorg-stderr-")
			log("stderr=%s for %s", stderr.name, cmd)
		xvfb = self.run_command(cmd_expanded, stdout=stdout, stderr=stderr)
		time.sleep(1)
		log("xvfb(%s)=%s" % (cmdstr, xvfb))
		assert pollwait(xvfb, XVFB_TIMEOUT) is None, "xvfb command \"%s\" failed and returned %s" % (cmdstr, xvfb.poll())
		return xvfb


	def run_server(self, *args):
		display = self.find_free_display()
		server = self.check_server("start", display, *args)
		server.display = display
		return server

	def check_start_server(self, display, *args):
		return self.check_server("start", display, *args)

	def check_server(self, subcommand, display, *args):
		cmd = [subcommand]
		if display:
			cmd.append(display)
		if not WIN32:
			cmd += ["--no-daemon"]
		cmd += list(args)
		server_proc = self.run_xpra(cmd)
		assert pollwait(server_proc, SERVER_TIMEOUT) is None, "server failed to start with '%s', returned %s" % (cmd, server_proc.poll())
		if display:
			#wait until the socket shows up:
			for _ in range(20):
				live = self.dotxpra.displays()
				if display in live:
					break
				time.sleep(1)
			assert server_proc.poll() is None, "server '%s' terminated and returned %s" % (cmd, server_proc.poll())
			assert display in live, "server display '%s' not found in live displays %s" % (display, live)
			#then wait a little before using it:
			time.sleep(1)
		#query it:
		version = None
		for _ in range(20):
			if version is None:
				args = ["version"]
				if display:
					args.append(display)
				version = self.run_xpra(args)
			r = pollwait(version, 1)
			log("version for %s returned %s", display, r)
			if r is not None:
				if r==1:
					#re-run it
					version = None
					continue
				break
			time.sleep(1)
		assert r==0, "version failed for %s, returned %s" % (display, r)
		return server_proc

	def stop_server(self, server_proc, subcommand="stop", *connect_args):
		if server_proc.poll() is not None:
			return
		cmd = [subcommand]+list(connect_args)
		stopit = self.run_xpra(cmd)
		assert pollwait(stopit, STOP_WAIT_TIMEOUT) is not None, "%s command failed to exit" % subcommand
		assert pollwait(server_proc, STOP_WAIT_TIMEOUT) is not None, "server process %s failed to exit" % server_proc

	def check_stop_server(self, server_proc, subcommand="stop", display=":99999"):
		self.stop_server(server_proc, subcommand, display)
		if display:
			assert display not in self.dotxpra.displays(), "server socket for display %s should have been removed" % display
