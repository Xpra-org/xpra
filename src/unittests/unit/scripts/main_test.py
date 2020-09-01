#!/usr/bin/env python
# -*- coding: utf-8 -*-
# This file is part of Xpra.
# Copyright (C) 2020 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import shlex
import unittest
from subprocess import Popen, DEVNULL, PIPE

from xpra.os_util import OSEnvContext, pollwait, WIN32, POSIX, OSX
from xpra.util import AdHocStruct
from xpra.platform.paths import get_xpra_command
from xpra.scripts.main import (
    nox,
    use_systemd_run, systemd_run_command, systemd_run_wrap,
    isdisplaytype,
    check_display,
    get_host_target_string,
    parse_display_name,
    )

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
            for log_systemd_wrap in (True, False):
                with OSEnvContext():
                    os.environ["XPRA_LOG_SYSTEMD_WRAP"] = str(log_systemd_wrap)
                    assert systemd_run_wrap("unused", ["xpra", "--version"])==0

    def test_display_type_check(self):
        for arg in ("ssh:host", "ssh/host", "tcp:IP", "ssl/host", "vsock:port"):
            args = [arg]
            assert isdisplaytype(args, "ssh", "tcp", "ssl", "vsock")

    def test_check_display(self):
        #only implemented properly on MacOS
        check_display()

    def test_ssh_parsing(self):
        #parse_ssh_string
        pass

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

    def test_parse_display_name(self):
        opts = AdHocStruct()
        opts.socket_dirs = ["/tmp"]
        if WIN32:
            assert parse_display_name(None, opts, "named-pipe:///FOO")==parse_display_name(None, opts, "FOO")
        else:
            assert parse_display_name(None, opts, "socket:///FOO")==parse_display_name(None, opts, "/FOO")

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
        except Exception:
            raise Exception("failed on %s" % (cmd,))

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
            "_sound_query",
            "invalid-command",
            ):
            self._test_subcommand(args)

    def test_terminate_subcommands(self):
        if POSIX and not OSX:
            return
        subcommands = [
            "initenv",
            "mdns-gui",
            "sessions",
            "launcher",
            "gui",
            "bug-report",
            "_dialog",
            "_pass",
            "send-file",
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
            proc.terminate()

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
