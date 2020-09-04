#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2018-2019 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import time
import unittest

from xpra.os_util import POSIX
from xpra.util import AdHocStruct
from unit.server.mixins.servermixintest_util import ServerMixinTest


class ChildCommandMixinTest(ServerMixinTest):

    def test_command_server(self):
        from xpra.server.mixins.child_command_server import ChildCommandServer
        opts = AdHocStruct()
        opts.exit_with_children = True
        opts.terminate_children = True
        opts.start_new_commands = True
        opts.start = []
        opts.start_child = []
        opts.start_after_connect = []
        opts.start_child_after_connect = []
        opts.start_on_connect = []
        opts.start_child_on_connect = []
        opts.start_on_last_client_exit = []
        opts.start_child_on_last_client_exit = []
        opts.exec_wrapper = None
        opts.start_env = []
        opts.source_start = []
        #pynotify can cause crashes,
        #probably due to threading issues?
        def noop():
            pass
        def _ChildCommandServer():
            ccs = ChildCommandServer()
            ccs.setup_menu_watcher = noop
            return ccs
        self._test_mixin_class(_ChildCommandServer, opts)
        if not POSIX:
            return
        #test creating a temp file:
        import tempfile
        tmpfile = os.path.join(tempfile.gettempdir(), "xpra-test-start-command-%s" % os.getpid())
        assert not os.path.exists(tmpfile)
        command = (b"touch", tmpfile.encode("utf8"))
        self.handle_packet(("start-command", b"test", command, True))
        time.sleep(1)
        info = self.mixin.get_info(self.protocol)
        commands = info.get("commands")
        assert commands
        proc_info = commands.get(0)
        assert proc_info
        pid = proc_info.get("pid")
        assert pid
        assert os.path.exists(tmpfile)
        os.unlink(tmpfile)
        #test signals:
        self.handle_packet(("start-command", b"sleep", b"sleep 10", True))
        time.sleep(1)
        info = self.mixin.get_info(self.protocol)
        commands = info.get("commands")
        assert commands
        proc_info = commands.get(1)
        assert proc_info
        pid = proc_info.get("pid")
        assert pid
        assert proc_info.get("name")=="sleep"
        assert proc_info.get("dead") is False
        #send it a SIGINT:
        self.handle_packet(("command-signal", pid, "SIGINT"))
        time.sleep(1)
        self.mixin.child_reaper.poll()
        info = self.mixin.get_info(self.protocol)
        commands = info.get("commands")
        assert commands
        proc_info = commands.get(1)
        assert proc_info.get("dead") is True
        import signal
        assert proc_info.get("returncode") == -signal.SIGINT


def main():
    unittest.main()


if __name__ == '__main__':
    main()
