#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from xpra.server.subsystem.process import ProcessServer


class ProcessServerTest(unittest.TestCase):

    @staticmethod
    def make_opts(**kwargs):
        opts = {
            "uid": os.getuid(),
            "gid": os.getgid(),
            "env": (),
            "source": (),
            "wm_name": "",
            "xvfb": "",
            "chdir": "",
        }
        opts.update(kwargs)
        return SimpleNamespace(**opts)

    def test_setup_configures_env_and_chdir(self):
        server = SimpleNamespace()
        opts = self.make_opts(env=("A=B",), chdir="/tmp")
        process = ProcessServer(server)
        with patch("xpra.server.subsystem.process.getuid", return_value=1), \
                patch("xpra.server.subsystem.process.configure_env") as configure_env, \
                patch("xpra.server.subsystem.process.os.chdir") as chdir:
            process.init(opts)
            process.setup()
            process.setup()
        configure_env.assert_called_once_with(opts.env)
        chdir.assert_called_once_with("/tmp")

    def test_setup_root_switches_user(self):
        server = SimpleNamespace()
        opts = self.make_opts(uid=1000, gid=1000, env=("A=B",))
        process = ProcessServer(server)
        with patch("xpra.server.subsystem.process.POSIX", True), \
                patch("xpra.server.subsystem.process.getuid", return_value=0), \
                patch("xpra.server.subsystem.process.get_username_for_uid", return_value="alice"), \
                patch("xpra.server.subsystem.process.get_home_for_uid", return_value="/home/alice"), \
                patch("xpra.server.subsystem.process.get_shell_for_uid", return_value="/bin/sh"), \
                patch("xpra.util.daemon.setuidgid") as setuidgid, \
                patch("xpra.server.subsystem.process.configure_env") as configure_env, \
                patch("xpra.server.subsystem.process.os.chdir") as chdir, \
                patch.dict(os.environ, {}, clear=True):
            process.init(opts)
            process.protected_env = {"PROTECTED": "1"}
            process.setup()
            assert os.environ["HOME"] == "/home/alice"
            assert os.environ["USER"] == "alice"
            assert os.environ["LOGNAME"] == "alice"
            assert os.environ["SHELL"] == "/bin/sh"
            assert os.environ["PROTECTED"] == "1"
        setuidgid.assert_called_once_with(1000, 1000)
        configure_env.assert_called_once_with(opts.env)
        chdir.assert_called_once_with("/home/alice")
        assert opts.chdir == ""
        assert process.chdir == "/home/alice"

    def test_get_info(self):
        server = SimpleNamespace()
        opts = self.make_opts(uid=1000, gid=1000, chdir="/tmp")
        process = ProcessServer(server)
        process.init(opts)
        with patch("xpra.server.subsystem.process.POSIX", True), \
                patch("xpra.server.subsystem.process.getuid", return_value=0):
            assert process.get_info(None) == {
                "process": {
                    "uid": 1000,
                    "gid": 1000,
                    "root": True,
                    "chdir": "/tmp",
                    "applied": False,
                },
            }


def main():
    unittest.main()


if __name__ == "__main__":
    main()
