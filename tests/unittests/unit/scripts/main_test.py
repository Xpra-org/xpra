#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# This file is part of Xpra.
# Copyright (C) 2020 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import shlex
import signal
import tempfile
import unittest
from subprocess import Popen, DEVNULL, PIPE

from xpra.os_util import getuid, POSIX, OSX
from xpra.util.env import OSEnvContext
from xpra.util.io import pollwait
from xpra.util.objects import AdHocStruct
from xpra.platform.paths import get_xpra_command
from xpra.common import noop, noerr
from xpra.scripts.config import InitException
from xpra.scripts.main import (
    nox, use_systemd_run, systemd_run_command, systemd_run_wrap,
    isdisplaytype,
    check_display,
    find_session_by_name,
    find_mode_pos,
    strip_attach_extra_positional_args,
)
from xpra.net.connect import connect_to, get_host_target_string


def _get_test_socket_dir():
    return tempfile.gettempdir()


class TestMain(unittest.TestCase):

    def test_nox(self):
        with OSEnvContext():
            os.environ["DISPLAY"] = "not-a-display"
            nox()
            assert os.environ.get("DISPLAY") is None

    def test_systemd_run(self):
        for s in ("yes", "no", "auto"):
            if not use_systemd_run(s):
                continue
            for user in (True, False):
                for systemd_run_args in ("", "-d"):
                    assert systemd_run_command("mode", systemd_run_args, user=user)[0]=="systemd-run"
        if not use_systemd_run("auto"):
            return
        with OSEnvContext():
            os.environ["XPRA_LOG_SYSTEMD_WRAP"] = "0"
            os.environ["XPRA_LOG_SYSTEMD_WRAP_COMMAND"] = "0"
            cmd = get_xpra_command()+["--version"]
            r = systemd_run_wrap("unused", cmd, user=getuid()!=0, stdout=DEVNULL, stderr=DEVNULL)
            if r:
                raise ValueError(f"expected return code 0 but got {r} running {cmd}")

    def test_display_type_check(self):
        for arg in ("ssh:host", "ssh/host", "tcp:IP", "ssl/host", "vsock:port"):
            args = [arg]
            assert isdisplaytype(args, "ssh", "tcp", "ssl", "vsock")

    def test_check_display(self):
        #only implemented properly on MacOS
        check_display()

    def test_find_mode_pos(self):
        for args in ([], [100], ["hello", "world"]):
            for v in (0, "a", ""):
                try:
                    find_mode_pos(args, v)
                except (InitException, TypeError):
                    pass
                else:
                    raise RuntimeError(f"find_mode_pos should have failed for {args} and {v}")
        args = [
            'xpra_cmd', 'start', 'ssl://[user]@[host]:[port]', '--ssl-server-verify-mode=none',
            '--no-microphone', '--no-speaker', '--no-webcam', '--no-printing', '--pulseaudio=no',
            '--start-child=rstudio',
        ]
        assert find_mode_pos(args, "seamless")==1

    def test_strip_attach_extra_positional_args(self):
        cmdline = ["xpra", "attach", "ssh://localhost/2", "dolphin"]
        assert strip_attach_extra_positional_args(cmdline) == ["xpra", "attach", "ssh://localhost/2"]

        cmdline = ["xpra", "attach", "ssh://localhost/2", "--encoding", "h264"]
        assert strip_attach_extra_positional_args(cmdline) == cmdline

        cmdline = ["xpra", "attach", "ssh://localhost/2", "--encoding", "h264", "dolphin"]
        assert strip_attach_extra_positional_args(cmdline) == ["xpra", "attach", "ssh://localhost/2", "--encoding", "h264"]

    def test_host_parsing(self):
        try:
            target = get_host_target_string({})
        except Exception:
            pass
        else:
            raise Exception("got host string '%s' without specifying any display attributes!" % target)

        def t(d, e):
            s = get_host_target_string(d)
            assert s==e, "expected '%s' for %s but got '%s'" % (e, d, s)
        t({"type" : "ssh", "username" : "foo", "host" : "bar"}, "ssh://foo@bar/")
        t({"type" : "ssh", "username" : "foo", "host" : "bar", "port" : -1}, "ssh://foo@bar/")
        t({"type" : "ssh", "username" : "foo", "host" : "bar", "port" : 2222}, "ssh://foo@bar:2222/")

    def test_find_session_by_name(self):
        socket_dir = _get_test_socket_dir()
        opts = AdHocStruct()
        opts.socket_dirs = [socket_dir]
        opts.socket_dir = socket_dir
        assert not find_session_by_name(opts, "not-a-valid-session")

    def test_connect_to(self):
        def f(**kwargs):
            fd(kwargs)

        def fd(d):
            opts = AdHocStruct()
            try:
                #silence errors since we're expecting them:
                from xpra.scripts import main as xpra_main
                saved_timeout = xpra_main.CONNECT_TIMEOUT
                saved_werr = xpra_main.werr
                try:
                    xpra_main.CONNECT_TIMEOUT = 5
                    xpra_main.werr = noop
                    conn = connect_to(d, opts)
                finally:
                    xpra_main.werr = saved_werr
                    xpra_main.CONNECT_TIMEOUT = saved_timeout
            except Exception:
                #from xpra.util import get_util_logger
                #get_util_logger().error("connect_to(%s, %s)", d, opts, exc_info=True)
                pass
            else:
                try:
                    conn.close()
                except Exception:
                    pass
                raise Exception("connect_to(%s) should have failed" % (d,))
        #without extra arguments to specify the endpoint,
        #all connections should fail, even if they have a valid type:
        f(type="invalid", display_name="test")
        f(type="vsock", display_name="test", vsock=(10, 1000))
        fd({"type" : "named-pipe", "display_name" : "test", "named-pipe" : "TEST-INVALID"})
        f(type="socket", display_name=":100000", display="100000")
        for socktype in ("tcp", "ssl", "ws", "wss", ):
            f(type=socktype, display_name="test", host="localhost", port=100000)
        for paramiko in (True, False):
            f(type="ssh", display_name="test", host="localhost", port=100000, is_paramiko=paramiko)
        fd({
            "type"              : "ssl",
            "display_name"      : "test",
            "host"              : "localhost",
            "port"              : 100000,
            "strict-host-check" : False,
        })

    def _test_subcommand(self, args, timeout=60, **kwargs):
        proc = self._run_subcommand(args, timeout, **kwargs)
        if proc.poll() is None:
            proc.terminate()
            raise Exception("%s did not terminate after %i seconds" % (args, timeout))

    def _run_subcommand(self, args, wait=60, **kwargs):
        cmd = get_xpra_command()+shlex.split(args)
        if "stdout" not in kwargs:
            kwargs["stdout"] = DEVNULL
        if "stderr" not in kwargs:
            kwargs["stderr"] = DEVNULL
        try:
            proc = Popen(cmd, **kwargs)
            pollwait(proc, wait)
            return proc
        except Exception as e:
            raise Exception("failed on %s" % (cmd,)) from e

    def test_nongui_subcommands(self):
        for args in (
            "initenv",
            "list",
            "list-windows",
            "showconfig",
            "showsetting xvfb",
            "encoding",
            "webcam",
            "keyboard",
            "keymap",
            "gui-info",
            "network-info",
            "path-info",
            "printing-info",
            "version-info",
            "gtk-info",
            "opengl", "opengl-probe",
            "help",
            "whatever --help",
            "start --speaker-codec=help",
            "start --microphone-codec=help",
            "attach --speaker-codec=help",
            "attach --microphone-codec=help",
            "_audio_query",
            "invalid-command",
        ):
            self._test_subcommand(args)

    def test_terminate_subcommands(self):
        if POSIX and not OSX:
            #can't test commands that require a display yet
            return
        subcommands = [
            "mdns-gui",
            "sessions",
            "launcher",
            "gui",
            "bug-report",
            "_dialog",
            "_pass",
            #"send-file", needs a server socket
            #"splash", has its own test module
            "clipboard-test",
            "keyboard-test",
            "toolbox",
            "colors-test",
            "colors-gradient-test",
            "transparent-colors",
        ]
        for args in subcommands:
            proc = self._run_subcommand(args, 10, stdout=PIPE, stderr=PIPE)
            r = proc.poll()
            if r is not None:
                raise Exception("%s subcommand should not have terminated" % (args,))
            noerr(proc.send_signal, signal.SIGTERM)
            if pollwait(proc, 2) is None:
                noerr(proc.terminate)
                if pollwait(proc, 2) is None:
                    noerr(proc.kill)

    def test_debug_option(self):
        for debug in ("all", "util", "platform,-import", "foo,,bar"):
            args = "version-info --debug %s" % debug
            self._test_subcommand(args, 20)

    def test_misc_env_switches(self):
        with OSEnvContext():
            os.environ["XPRA_NOMD5"] = "1"
            self._test_subcommand("version-info")


def main():
    unittest.main()


if __name__ == '__main__':
    main()
