#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2016-2019 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import sys
import time
import subprocess

from unit.process_test_util import ProcessTestUtil
from xpra.util import envint
from xpra.os_util import pollwait, bytestostr, POSIX, WIN32
from xpra.platform.dotxpra import DotXpra
from xpra.platform.paths import get_xpra_command
from xpra.log import Logger

log = Logger("test")

SERVER_TIMEOUT = envint("XPRA_TEST_SERVER_TIMEOUT", 8)
STOP_WAIT_TIMEOUT = envint("XPRA_STOP_WAIT_TIMEOUT", 20)


class ServerTestUtil(ProcessTestUtil):

    @classmethod
    def displays(cls):
        if not POSIX:
            return []
        return cls.dotxpra.displays()

    @classmethod
    def setUpClass(cls):
        ProcessTestUtil.setUpClass()
        tmpdir = os.environ.get("TMPDIR", "/tmp")
        cls.dotxpra = DotXpra(tmpdir, [tmpdir])
        cls.default_xpra_args = ["--speaker=no", "--microphone=no"]
        if not WIN32:
            cls.default_xpra_args += ["--systemd-run=no", "--pulseaudio=no"]
            for x in cls.dotxpra._sockdirs:
                cls.default_xpra_args += ["--socket-dirs=%s" % x]
        cls.existing_displays = cls.displays()

    @classmethod
    def tearDownClass(cls):
        ProcessTestUtil.tearDownClass()
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
        if cls.xauthority_temp:
            try:
                os.unlink(cls.xauthority_temp.name)
            except OSError as e:
                log.error("Error deleting '%s': %s", cls.xauthority_temp.name, e)
            cls.xauthority_temp = None


    def setUp(self):
        ProcessTestUtil.setUp(self)
        xpra_list = self.run_xpra(["list"])
        assert pollwait(xpra_list, 15) is not None, "xpra list returned %s" % xpra_list.poll()


    def run_xpra(self, xpra_args, env=None, **kwargs):
        cmd = self.get_xpra_cmd()+list(xpra_args)
        return self.run_command(cmd, env, **kwargs)

    @classmethod
    def get_xpra_cmd(cls):
        xpra_cmd = get_xpra_command()
        if xpra_cmd==["xpra"]:
            xpra_cmd = [bytestostr(cls.which("xpra"))]
        cmd = xpra_cmd + cls.default_xpra_args
        pyexename = "python%i" % sys.version_info[0]
        exe = bytestostr(xpra_cmd[0]).rstrip(".exe")
        if not (exe.endswith("python") or exe.endswith(pyexename)):
            #prepend python2 / python3:
            cmd = [pyexename] + xpra_cmd + cls.default_xpra_args
        return cmd


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
        if pollwait(server_proc, SERVER_TIMEOUT) is not None:
            self.show_proc_error(server_proc, "server failed to start")
        if display:
            #wait until the socket shows up:
            for _ in range(20):
                live = self.dotxpra.displays()
                if display in live:
                    break
                time.sleep(1)
            if server_proc.poll() is not None:
                self.show_proc_error(server_proc, "server terminated")
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
        if r!=0:
            self.show_proc_error(version, "version check failed for %s, returned %s" % (display, r))
        return server_proc

    def stop_server(self, server_proc, subcommand, *connect_args):
        assert subcommand in ("stop", "exit")
        if server_proc.poll() is not None:
            raise Exception("cannot stop server, it has already exited, returncode=%i" % server_proc.poll())
        cmd = [subcommand]+list(connect_args)
        stopit = self.run_xpra(cmd)
        if pollwait(stopit, STOP_WAIT_TIMEOUT) is None:
            log.warn("failed to stop %s:", server_proc)
            self.show_proc_pipes(server_proc)
            self.show_proc_error(stopit, "stop server error")
        assert pollwait(server_proc, STOP_WAIT_TIMEOUT) is not None, "server process %s failed to exit" % server_proc

    def check_stop_server(self, server_proc, subcommand="stop", display=":99999"):
        self.stop_server(server_proc, subcommand, display)
        if display and display in self.dotxpra.displays():
            raise Exception("server socket for display %s should have been removed" % display)
