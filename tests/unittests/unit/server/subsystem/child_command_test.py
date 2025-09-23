#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2018 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import time
import unittest
from contextlib import nullcontext

from xpra.os_util import POSIX
from xpra.util.child_reaper import get_child_reaper
from xpra.util.objects import AdHocStruct
from unit.test_util import silence_info
from unit.server.subsystem.servermixintest_util import ServerMixinTest


class ChildCommandMixinTest(ServerMixinTest):

    def test_command_server(self):
        try:
            from xpra.platform.posix.xdg_helper import log
            c = silence_info(log)
        except ImportError:
            c = nullcontext()
        with c:
            self.do_test_command_server()

    def do_test_command_server(self):
        from xpra.server.subsystem import command
        opts = AdHocStruct()
        opts.exit_with_children = True
        opts.terminate_children = True
        opts.start_new_commands = True
        opts.start = []
        opts.start_child = []
        opts.start_late = []
        opts.start_child_late = []
        opts.start_after_connect = []
        opts.start_child_after_connect = []
        opts.start_on_connect = []
        opts.start_child_on_connect = []
        opts.start_on_disconnect = []
        opts.start_child_on_disconnect = []
        opts.start_on_last_client_exit = []
        opts.start_child_on_last_client_exit = []
        opts.exec_wrapper = None
        opts.start_env = []
        opts.source_start = []
        opts.chdir = ""

        # pynotify can cause crashes,
        # probably due to threading issues?

        def noop():
            pass

        def _ChildCommandServer():
            ccs = command.ChildCommandServer()
            ccs.setup_menu_watcher = noop
            return ccs

        self._test_mixin_class(_ChildCommandServer, opts)
        if not POSIX:
            return
        # test creating a temp file:
        import tempfile
        tmpfile = os.path.join(tempfile.gettempdir(), "xpra-test-start-command-%s" % os.getpid())
        assert not os.path.exists(tmpfile)
        cmd = ("touch", tmpfile)
        with silence_info(command):
            self.handle_packet(("start-command", "test", cmd, True))
        time.sleep(1)
        info = self.mixin.get_info(self.protocol)
        commands = info.get("command")
        assert commands
        proc_info = commands.get(0)
        assert proc_info
        pid = proc_info.get("pid")
        assert pid
        assert os.path.exists(tmpfile)
        os.unlink(tmpfile)
        # test signals:
        with silence_info(command):
            self.handle_packet(("start-command", "sleep", "sleep 10", True))
        time.sleep(1)
        info = self.mixin.get_info(self.protocol)
        commands = info.get("command")
        assert commands
        proc_info = commands.get(1)
        assert proc_info
        pid = proc_info.get("pid")
        assert pid
        assert proc_info.get("name") == "sleep"
        assert proc_info.get("dead") is False
        # send it a SIGINT:
        with silence_info(command):
            self.handle_packet(("command-signal", pid, "SIGINT"))
        time.sleep(1)
        get_child_reaper().poll()
        info = self.mixin.get_info(self.protocol)
        commands = info.get("command")
        assert commands
        proc_info = commands.get(1)
        assert proc_info.get("dead") is True
        import signal
        assert proc_info.get("returncode") == -signal.SIGINT


def main():
    unittest.main()


if __name__ == '__main__':
    main()
