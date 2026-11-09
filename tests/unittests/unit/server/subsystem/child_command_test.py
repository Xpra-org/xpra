#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2018 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import time
import unittest
from contextlib import nullcontext
from unittest.mock import Mock, patch

from xpra.net.packet_type import COMMAND_START
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

        # `setup_menu_watcher` belongs to `MenuProvider` (see `xpra/server/menu_provider.py`),
        # not to this subsystem: stubbing it here never had any effect.
        self._test_mixin_class(command.ChildCommandServer, opts)
        if not POSIX:
            return
        # test creating a temp file:
        import tempfile
        tmpfile = os.path.join(tempfile.gettempdir(), "xpra-test-start-command-%s" % os.getpid())
        assert not os.path.exists(tmpfile)
        cmd = ("touch", tmpfile)
        with silence_info(command):
            self.handle_packet((COMMAND_START, "test", cmd, True))
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
            self.handle_packet((COMMAND_START, "sleep", "sleep 10", True))
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


class ChildCommandReadonlyTest(unittest.TestCase):

    def test_readonly_start_and_signal(self):
        from xpra.server.subsystem.command import ChildCommandServer
        from xpra.net.common import Packet

        for readonly in (True, False):
            with self.subTest(readonly=readonly):
                server = AdHocStruct()
                server.is_readonly = lambda _proto: readonly
                server.start_new_commands = True
                server.get_server_source = lambda _proto: None
                server.start_command = Mock(return_value=None)
                with patch("xpra.server.subsystem.command.log"):
                    ChildCommandServer._process_start(server, object(), Packet(COMMAND_START, "test", "true", True))
                self.assertEqual(server.start_command.called, not readonly)
                procinfo = AdHocStruct()
                procinfo.returncode = None
                with (
                    patch("xpra.server.subsystem.command.COMMAND_SIGNALS", ("SIGTERM", )),
                    patch("xpra.server.subsystem.command.get_child_reaper") as reaper,
                    patch("xpra.server.subsystem.command.send_signame") as send_signame,
                    patch("xpra.server.subsystem.command.log"),
                ):
                    reaper.return_value.get_proc_info.return_value = procinfo
                    ChildCommandServer._process_signal(server, object(), Packet("command-signal", 1234, "SIGTERM"))
                    self.assertEqual(send_signame.called, not readonly)

    def test_server_core_is_readonly(self):
        from xpra.server.core import ServerCore
        ss = AdHocStruct()
        ss.effective_readonly = lambda: True
        server = AdHocStruct()
        server.readonly = False
        server.get_server_source = lambda _proto: ss
        self.assertFalse(ServerCore.is_readonly(server))
        self.assertTrue(ServerCore.is_readonly(server, "proto"))
        ss.effective_readonly = lambda: False
        self.assertFalse(ServerCore.is_readonly(server, "proto"))
        server.readonly = True
        self.assertTrue(ServerCore.is_readonly(server, "proto"))


def main():
    unittest.main()


if __name__ == '__main__':
    main()
