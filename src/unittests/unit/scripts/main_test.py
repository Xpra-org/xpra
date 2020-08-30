#!/usr/bin/env python
# -*- coding: utf-8 -*-
# This file is part of Xpra.
# Copyright (C) 2020 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import shlex
import unittest
from subprocess import Popen, DEVNULL

from xpra.os_util import OSEnvContext, pollwait
from xpra.scripts.main import (
    nox,
    use_systemd_run, systemd_run_command, systemd_run_wrap,
    isdisplaytype,
    check_display,
    get_host_target_string,
    )

class TestMain(unittest.TestCase):

    def test_nox(self):
        with OSEnvContext():
            os.environ["DISPLAY"] = "not-a-display"
            nox()
            assert os.environ.get("DISPLAY") is None

    def test_systemd_run(self):
        for s in ("yes", "no"):
            if not use_systemd_run(s):
                continue
            for user in (True, False):
                for systemd_run_args in ("", "-d"):
                    assert systemd_run_command("mode", systemd_run_args, user=user)[0]=="systemd-run"
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
        d = {
            }
        def t(d, e):
            s = get_host_target_string(d)
            assert s==e, "expected '%s' for %s but got '%s'" % (e, d, s)
        t({"type" : "ssh", "username" : "foo", "host" : "bar"}, "ssh://foo@bar/")
        t({"type" : "ssh", "username" : "foo", "host" : "bar", "port" : 2222}, "ssh://foo@bar:2222/")


    def test_nongui_subcommands(self):
        from xpra.platform.paths import get_xpra_command
        for args in (
            "list",
            "list-windows",
            "showconfig",
            ):
            cmd = get_xpra_command()+shlex.split(args)
            try:
                proc = Popen(cmd, stdout=DEVNULL, stderr=DEVNULL)
                timeout = 60
                if pollwait(proc, timeout) is None:
                    proc.terminate()
                    raise Exception("%s did not terminate after %i seconds" % (cmd, timeout))
            except Exception:
                raise Exception("failed on %s" % (cmd,))


def main():
    unittest.main()

if __name__ == '__main__':
    main()
