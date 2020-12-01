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
from xpra.platform.paths import get_xpra_command
from xpra.platform.dotxpra import DISPLAY_PREFIX
from xpra.scripts.config import get_defaults

from xpra.log import Logger
log = Logger("test")

XPRA_TEST_DEBUG = envbool("XPRA_TEST_DEBUG", False)
XVFB_TIMEOUT = envint("XPRA_TEST_XVFB_TIMEOUT", 8)
DELETE_TEMP_FILES = envbool("XPRA_DELETE_TEMP_FILES", True)
SHOW_XORG_OUTPUT = envbool("XPRA_SHOW_XORG_OUTPUT", False)
TEST_XVFB_COMMAND = os.environ.get("XPRA_TEST_VFB_COMMAND", "Xvfb")


def show_proc_pipes(proc):
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

def show_proc_error(proc, msg):
    if not proc:
        raise Exception("command failed to start: %s" % msg)
    log.warn("%s failed:", proc.command)
    log.warn("returncode=%s", proc.poll())
    show_proc_pipes(proc)
    raise Exception(msg+" command=%s" % proc.command)


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
            os.environ["DISPLAY"] = self.xvfb_process.display or ""
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
        cls.display_start = 100
        cls.temp_files = []
        cls.processes = []
        from xpra.server.server_util import find_log_dir
        cls.xauthority_temp = None #tempfile.NamedTemporaryFile(prefix="xpra-test.", suffix=".xauth", delete=False)
        #cls.xauthority_temp.close()
        #os.environ["XAUTHORITY"] = os.path.expanduser(cls.xauthority_temp.name)
        cls.default_env = os.environ.copy()
        cls.default_env.update({
            "XPRA_LOG_DIR"  : find_log_dir(),
            "XPRA_NOTTY"    : "1",
            "XPRA_WAIT_FOR_INPUT"   : "0",
            "XPRA_FLATTEN_INFO"     : "0",
            })
        cls.default_config = get_defaults()
        log("setUpClass(%s) default_env=%s", cls, cls.default_env)

    @classmethod
    def tearDownClass(cls):
        if cls.xauthority_temp:
            os.unlink(cls.xauthority_temp.name)
        cls.stop_commands()
        if DELETE_TEMP_FILES:
            for x in cls.temp_files:
                try:
                    os.unlink(x)
                except OSError:
                    pass

    @classmethod
    def stop_commands(cls):
        for x in cls.processes:
            try:
                if x.poll() is None:
                    x.terminate()
                stdout_file = getattr(x, "stdout_file", None)
                if stdout_file:
                    try:
                        stdout_file.close()
                    except OSError:
                        pass
                stderr_file = getattr(x, "stderr_file", None)
                if stderr_file:
                    try:
                        stderr_file.close()
                    except OSError:
                        pass
            except OSError:
                log.error("failed to stop subprocess %s", x)
        def get_wait_for():
            return tuple(proc for proc in cls.processes if proc.poll() is None)
        wait_for = get_wait_for()
        start = monotonic_time()
        while wait_for and monotonic_time()-start<5:
            if len(wait_for)==1:
                pollwait(wait_for[0])
            else:
                time.sleep(1)
            wait_for = get_wait_for()

    def setUp(self):
        os.environ.clear()
        os.environ.update(self.default_env)


    @classmethod
    def get_default_run_env(cls):
        env = dict((k,v) for k,v in cls.default_env.items() if
                k.startswith("XPRA") or k in (
                    "HOME", "HOSTNAME", "SHELL", "TERM",
                    "USER", "USERNAME", "PATH",
                    "XAUTHORITY", "PWD",
                    "PYTHONPATH", "SYSTEMROOT",
                    ))
        log("get_default_run_env() env(%s)=%s", repr_ellipsized(cls.default_env), env)
        env["NO_AT_BRIDGE"] = "1"
        return env

    def get_run_env(self):
        return self.get_default_run_env()


    @classmethod
    def which(cls, cmd):
        try:
            from xpra.os_util import get_status_output
            code, out, _ = get_status_output(["which", cmd])
            if code==0:
                return out.splitlines()[0]
        except OSError:
            pass
        return cmd

    def run_command(self, command, **kwargs):
        return self.class_run_command(command, **kwargs)

    @classmethod
    def class_run_command(cls, command, **kwargs):
        if "env" not in kwargs:
            kwargs["env"] = cls.get_default_run_env()
        stdout_file = stderr_file = None
        if isinstance(command, (list, tuple)):
            strcommand = " ".join("'%s'" % x for x in command)
        else:
            strcommand = command
        if XPRA_TEST_DEBUG:
            log("************************")
            log("class_run_command(%s, %s)", command, repr_ellipsized(str(kwargs), 80))
            log("************************")
        else:
            if "stdout" not in kwargs:
                stdout_file = cls._temp_file(prefix="xpra-stdout-")
                kwargs["stdout"] = stdout_file
                log("stdout: %s for %s", stdout_file.name, strcommand)
            if "stderr" not in kwargs:
                stderr_file = cls._temp_file(prefix="xpra-stderr-")
                kwargs["stderr"] = stderr_file
                log("stderr: %s for %s", stderr_file.name, strcommand)
        try:
            log("class_run_command%s", (command, kwargs))
            proc = subprocess.Popen(args=command, **kwargs)
            proc.command = command
            proc.stdout_file = stdout_file
            proc.stderr_file = stderr_file
        except OSError as e:
            log.warn("class_run_command(%s, %s) %s", command, kwargs, e)
            raise
        cls.processes.append(proc)
        return proc


    @classmethod
    def get_xpra_cmd(cls):
        cmd = get_xpra_command()
        if cmd==["xpra"]:
            cmd = [bytestostr(cls.which("xpra"))]
        pyexename = "python3"
        exe = bytestostr(cmd[0])
        if exe.endswith(".exe"):
            exe = exe[:-4]
        if not (exe.endswith("python") or exe.endswith(pyexename) or exe=="coverage"):
            #prepend python / python3:
            cmd = [pyexename] + cmd
        return cmd


    @classmethod
    def show_proc_pipes(cls, proc):
        show_proc_pipes(proc)

    @classmethod
    def show_proc_error(cls, proc, msg):
        show_proc_error(proc, msg)


    @classmethod
    def get_command_output(cls, command, env=None, **kwargs):
        proc = cls.class_run_command(command, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, **kwargs)
        out = proc.communicate()[0]
        return out


    @classmethod
    def _temp_file(cls, data=None, prefix="xpra-"):
        f = tempfile.NamedTemporaryFile(prefix=prefix, delete=False)
        if data:
            f.file.write(data)
        f.file.flush()
        cls.temp_files.append(f.name)
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
        return ["%s%i" % (DISPLAY_PREFIX, x) for x in cls.find_X11_display_numbers()]


    @classmethod
    def find_free_display_no(cls, exclude=()):
        #X11 sockets:
        X11_displays = cls.find_X11_displays()
        start = cls.display_start % 10000
        for i in range(start, 20000):
            display = "%s%s" % (DISPLAY_PREFIX, i)
            if display in exclude:
                continue
            if display in X11_displays:
                continue
            cls.display_start += 100
            return i
        raise Exception("failed to find any free displays!")

    @classmethod
    def find_free_display(cls):
        return "%s%i" % (DISPLAY_PREFIX, cls.find_free_display_no())


    @classmethod
    def start_Xvfb(cls, display=None, screens=((1024,768),), depth=24, extensions=("Composite", )):
        assert POSIX
        if display is None:
            display = cls.find_free_display()
        env = {}
        for x in list(os.environ.keys()):
            if x in (
				"LOGNAME", "USER", "PATH", "LANG", "TERM",
				"HOME", "USERNAME", "PYTHONPATH", "HOSTNAME",
                #"XAUTHORITY",
				):    #DBUS_SESSION_BUS_ADDRESS
                #keep it
                env[x] = os.environ.get(x)
        real_display = os.environ.get("DISPLAY")
        cmd = [cls.which(TEST_XVFB_COMMAND)]
        is_xephyr = TEST_XVFB_COMMAND.find("Xephyr")>=0
        if is_xephyr:
            if len(screens)>1 or not real_display:
                #we can't use Xephyr for multi-screen
                cmd = [cls.which("Xvfb")]
            elif real_display:
                env["DISPLAY"] = real_display
        for ext in extensions:
            if ext.startswith("-"):
                cmd += ["-extension", ext[1:]]
            else:
                cmd += ["+extension", ext]
        cmd += ["-nolisten", "tcp", "-noreset"]
        #"-auth", self.default_env["XAUTHORITY"]]
        depth_str = "%i+%i" % (depth, 32)
        for i, screen in enumerate(screens):
            (w, h) = screen
            cmd += ["-screen"]
            if not is_xephyr:
                cmd += ["%i" % i]
            cmd += ["%ix%ix%s" % (w, h, depth_str)]
        cmd.append(display)
        env["XPRA_LOG_DIR"] = "/tmp"
        cmd_expanded = [osexpand(v) for v in cmd]
        cmdstr = " ".join("'%s'" % x for x in cmd_expanded)
        if SHOW_XORG_OUTPUT:
            stdout = sys.stdout
            stderr = sys.stderr
        else:
            stdout = cls._temp_file(prefix="Xorg-stdout-")
            log("stdout=%s for %s", stdout.name, cmd)
            stderr = cls._temp_file(prefix="Xorg-stderr-")
            log("stderr=%s for %s", stderr.name, cmd)
        xvfb = cls.class_run_command(cmd_expanded, env=env, stdout=stdout, stderr=stderr)
        xvfb.display = display
        time.sleep(1)
        log("xvfb(%s)=%s" % (cmdstr, xvfb))
        if pollwait(xvfb, XVFB_TIMEOUT) is not None:
            show_proc_error(xvfb, "xvfb command \"%s\" failed and returned %s" % (cmdstr, xvfb.poll()))
        return xvfb
