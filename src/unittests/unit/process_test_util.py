#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2016-2019 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import sys
import time
import tempfile
import unittest
import subprocess

from xpra.util import envbool, envint, repr_ellipsized
from xpra.os_util import (
    OSX, OSEnvContext, POSIX,
    pollwait, osexpand, bytestostr, monotonic_time,
    )
from xpra.scripts.config import get_defaults

from xpra.log import Logger
log = Logger("test")

XPRA_TEST_DEBUG = envbool("XPRA_TEST_DEBUG", False)
XVFB_TIMEOUT = envint("XPRA_TEST_XVFB_TIMEOUT", 8)
DELETE_TEMP_FILES = envbool("XPRA_DELETE_TEMP_FILES", True)
SHOW_XORG_OUTPUT = envbool("XPRA_SHOW_XORG_OUTPUT", False)


class DisplayContext(OSEnvContext):

    def __init__(self):
        OSEnvContext.__init__(self)
        self.xvfb_process = None
    def __enter__(self):
        OSEnvContext.__enter__(self)
        if POSIX and not OSX:
            ProcessTestUtil.setUpClass()
            self.stu = ProcessTestUtil()
            self.stu.setUp()
            self.xvfb_process = self.stu.start_Xvfb()
            os.environ["GDK_BACKEND"] = "x11"
            os.environ["DISPLAY"] = self.xvfb_process.display
            from xpra.x11.gtk_x11.gdk_display_source import init_gdk_display_source
            init_gdk_display_source()

    def __exit__(self, *_args):
        if self.xvfb_process:
            self.xvfb_process.terminate()
            self.xvfb_process = None
            self.stu.tearDown()
            ProcessTestUtil.tearDownClass()
        OSEnvContext.__exit__(self)
    def __repr__(self):
        return "DisplayContext"


class ProcessTestUtil(unittest.TestCase):

    def __init__(self, methodName='runTest'):
        if not hasattr(self, "runTest"):
            self.runTest = None
        unittest.TestCase.__init__(self, methodName)

    @classmethod
    def setUpClass(cls):
        from xpra.server.server_util import find_log_dir
        cls.xauthority_temp = None #tempfile.NamedTemporaryFile(prefix="xpra-test.", suffix=".xauth", delete=False)
        #cls.xauthority_temp.close()
        #os.environ["XAUTHORITY"] = os.path.expanduser(cls.xauthority_temp.name)
        os.environ["XPRA_LOG_DIR"] = find_log_dir()
        os.environ["XPRA_NOTTY"] = "1"
        os.environ["XPRA_WAIT_FOR_INPUT"] = "0"
        os.environ["XPRA_FLATTEN_INFO"] = "0"
        os.environ["XPRA_NOTTY"] = "1"
        cls.default_env = os.environ.copy()
        cls.default_config = get_defaults()
        cls.display_start = 100+sys.version_info[0]

    @classmethod
    def tearDownClass(cls):
        if cls.xauthority_temp:
            os.unlink(cls.xauthority_temp.name)


    def setUp(self):
        os.environ.clear()
        os.environ.update(self.default_env)
        self.temp_files = []
        self.processes = []

    def tearDown(self):
        self.stop_commands()
        if DELETE_TEMP_FILES:
            for x in self.temp_files:
                try:
                    os.unlink(x)
                except (OSError, IOError):
                    pass

    def stop_commands(self):
        for x in self.processes:
            try:
                if x.poll() is None:
                    x.terminate()
                stdout_file = getattr(x, "stdout_file", None)
                if stdout_file:
                    try:
                        stdout_file.close()
                    except (OSError, IOError):
                        pass
                stderr_file = getattr(x, "stderr_file", None)
                if stderr_file:
                    try:
                        stderr_file.close()
                    except (OSError, IOError):
                        pass
            except (OSError, IOError):
                log.error("failed to stop subprocess %s", x)
        def get_wait_for():
            return tuple(proc for proc in self.processes if proc.poll() is None)
        wait_for = get_wait_for()
        start = monotonic_time()
        while wait_for and monotonic_time()-start<5:
            if len(wait_for)==1:
                pollwait(wait_for[0])
            else:
                time.sleep(1)
            wait_for = get_wait_for()


    def get_run_env(self):
        env = dict((k,v) for k,v in self.default_env.items() if
                k.startswith("XPRA") or k in (
                    "HOME", "HOSTNAME", "SHELL", "TERM",
                    "USER", "USERNAME", "PATH",
                    "XAUTHORITY", "PWD",
                    "PYTHONPATH", "SYSTEMROOT",
                    ))
        return env

    @classmethod
    def which(cls, cmd):
        try:
            from xpra.os_util import get_status_output, strtobytes
            code, out, _ = get_status_output(["which", cmd])
            if code==0:
                return strtobytes(out.splitlines()[0])
        except (OSError, IOError):
            pass
        return cmd

    def run_command(self, command, env=None, **kwargs):
        if env is None:
            env = kwargs.get("env") or self.get_run_env()
        kwargs["env"] = env
        stdout_file = stderr_file = None
        if isinstance(command, (list, tuple)):
            strcommand = " ".join("'%s'" % x for x in command)
        else:
            strcommand = command
        if XPRA_TEST_DEBUG:
            log("************************")
            log("run_command(%s, %s)", command, repr_ellipsized(str(env), 40))
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
            proc.command = command
            proc.stdout_file = stdout_file
            proc.stderr_file = stderr_file
        except OSError as e:
            log.warn("run_command(%s, %s, %s) %s", command, env, kwargs, e)
            raise
        self.processes.append(proc)
        return proc

    def show_proc_pipes(self, proc):
        def showfile(fileobj, filetype="stdout"):
            if fileobj and fileobj.name and os.path.exists(fileobj.name):
                log.warn("contents of %s file '%s':", filetype, fileobj.name)
                try:
                    with fileobj as f:
                        f.seek(0)
                        for line in f:
                            log.warn(" %s", bytestostr(line.rstrip(b"\n\r")))
                except Exception as e:
                    log.error("Error: failed to read '%s': %s", fileobj.name, e)
            else:
                log.warn("no %s file", filetype)
        showfile(proc.stdout_file, "stdout")
        showfile(proc.stderr_file, "stderr")

    def show_proc_error(self, proc, msg):
        if not proc:
            raise Exception("command failed to start: %s" % msg)
        log.warn("%s failed:", proc.command)
        log.warn("returncode=%s", proc.poll())
        self.show_proc_pipes(proc)
        raise Exception(msg+" command=%s" % proc.command)


    def get_command_output(self, command, env=None, **kwargs):
        proc = self.run_command(command, env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, **kwargs)
        out = proc.communicate()[0]
        return out


    def _temp_file(self, data=None, prefix="xpra-"):
        f = tempfile.NamedTemporaryFile(prefix=prefix, delete=False)
        if data:
            f.file.write(data)
        f.file.flush()
        self.temp_files.append(f.name)
        return f

    def delete_temp_file(self, f):
        try:
            self.temp_files.remove(f.name)
        except ValueError:
            pass
        try:
            os.unlink(f.name)
        except OSError as e:
            log.error("Error deleting temp file '%s': %s", f.name, e)


    @classmethod
    def find_X11_display_numbers(cls):
        #use X11 sockets:
        X11_displays = set()
        if POSIX and os.path.exists("/tmp/.X11-unix"):
            for x in os.listdir("/tmp/.X11-unix"):
                if x.startswith("X"):
                    try:
                        X11_displays.add(int(x[1:]))
                    except ValueError:
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
        start = cls.display_start % 10000
        for i in range(start, 20000):
            display = ":%i" % i
            if display and display not in X11_displays:
                cls.display_start += 100
                return i
        raise Exception("failed to find any free displays!")

    @classmethod
    def find_free_display(cls):
        return ":%i" % cls.find_free_display_no()


    def start_Xvfb(self, display=None, screens=((1024,768),)):
        assert POSIX
        if display is None:
            display = self.find_free_display()
        env = {}
        for x in list(os.environ.keys()):
            if x in (
				"LOGNAME", "USER", "PATH", "LANG", "TERM",
				"HOME", "USERNAME", "PYTHONPATH", "HOSTNAME",
                #"XAUTHORITY",
				):    #DBUS_SESSION_BUS_ADDRESS
                #keep it
                env[x] = os.environ.get(x)
        cmd = ["Xvfb", "+extension", "Composite", "-nolisten", "tcp", "-noreset"]
                #"-auth", self.default_env["XAUTHORITY"]]
        for i, screen in enumerate(screens):
            (w, h) = screen
            cmd += ["-screen", "%i" % i, "%ix%ix24+32" % (w, h)]
        cmd.append(display)
        env["DISPLAY"] = display
        env["XPRA_LOG_DIR"] = "/tmp"
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
        xvfb = self.run_command(cmd_expanded, env=env, stdout=stdout, stderr=stderr)
        xvfb.display = display
        time.sleep(1)
        log("xvfb(%s)=%s" % (cmdstr, xvfb))
        if pollwait(xvfb, XVFB_TIMEOUT) is not None:
            self.show_proc_error(xvfb, "xvfb command \"%s\" failed and returned %s" % (cmdstr, xvfb.poll()))
        return xvfb
