#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2018 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import signal
import subprocess
import sys
import time
import unittest
from contextlib import nullcontext
from select import select
from textwrap import dedent
from unittest.mock import Mock, patch

from xpra.net.packet_type import COMMAND_START
from xpra.os_util import POSIX, OPENBSD
from xpra.util.child_reaper import ChildReaper, get_child_reaper
from xpra.util.objects import AdHocStruct
from unit.test_util import silence_info
from unit.server.subsystem.servermixintest_util import ServerMixinTest


class ChildCommandMixinTest(ServerMixinTest):

    @unittest.skipIf(OPENBSD, "signal delivery to child commands differs on OpenBSD")
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
        assert proc_info.get("returncode") == -signal.SIGINT


class ChildCommandProcessGroupTest(unittest.TestCase):

    def setUp(self):
        from xpra.server.subsystem import command
        server = Mock()
        server.get_child_env.return_value = os.environ.copy()
        self.command = command.ChildCommandServer(server)

    def test_launch_process_group(self):
        from xpra.server.subsystem import command
        callback = Mock()
        for enabled, posix in ((True, True), (False, True), (True, False), (False, False)):
            with self.subTest(enabled=enabled, posix=posix), \
                    patch.object(command, "KILL_CHILD_PROCESS_GROUP", enabled), patch.object(command, "POSIX", posix), \
                    patch.object(command, "Popen") as popen, patch.object(command, "get_child_reaper") as reaper, \
                    patch.dict(os.environ, {"XPRA_SESSION_DIR": ""}), silence_info(command):
                self.command.start_command("test", ["test"], callback=callback)
                self.assertEqual(popen.call_args.kwargs.get("start_new_session", False), enabled and posix)
                reaper.return_value.add_process.assert_called_once_with(
                    popen.return_value, "test", ["test"], ignore=False, callback=callback, kill_process_group=enabled and posix)

    @unittest.skipUnless(POSIX, "requires POSIX process groups and fork")
    def test_descendant_cleanup(self):
        from xpra.server.subsystem import command
        script = dedent("""\
            import os, signal, sys
            if os.fork() == 0:
                def terminated(*args):
                    os.write(1, b'terminated\\n')
                    os._exit(0)
                signal.signal(signal.SIGTERM, terminated)
                print(os.getpid(), os.getpgrp(), os.getsid(0), flush=True)
                while True:
                    signal.pause()
            sys.stdin.buffer.read(1)
            sys.exit(int(sys.argv[1]))
            """)
        for enabled in (False, True):
            for returncode in (0, 7, -signal.SIGKILL):
                with self.subTest(enabled=enabled, returncode=returncode), \
                        patch.object(command, "KILL_CHILD_PROCESS_GROUP", enabled), \
                        patch("xpra.util.child_reaper.GLib.timeout_add"), \
                        patch("xpra.util.child_reaper.GLib.idle_add") as idle_add, \
                        patch.dict(os.environ, {"XPRA_SESSION_DIR": ""}), silence_info(command):
                    reaper = ChildReaper()
                    callback = Mock()
                    with patch.object(command, "get_child_reaper", return_value=reaper):
                        proc = self.command.start_command("test", [sys.executable, "-c", script, str(returncode)],
                                                          ignore=True, callback=callback, stdin=subprocess.PIPE,
                                                          stdout=subprocess.PIPE, bufsize=0)
                    self.assertIsNotNone(proc)
                    descendant = 0
                    descendant_done = False

                    def read_line():
                        self.assertTrue(select([proc.stdout], [], [], 5)[0], "timed out waiting for descendant output")
                        return proc.stdout.readline()

                    try:
                        descendant, pgid, sid = map(int, read_line().split())
                        self.assertEqual(pgid, proc.pid if enabled else os.getpgrp())
                        self.assertEqual(sid, proc.pid if enabled else os.getsid(0))
                        if returncode < 0:
                            proc.kill()
                        else:
                            proc.stdin.write(b"x")
                        self.assertEqual(proc.wait(timeout=5), returncode)
                        info = reaper.get_proc_info(proc.pid)
                        # Also exercise shutdown: no GLib callback is ever drained.
                        if returncode == 7:
                            reaper.cleanup()
                        else:
                            reaper.poll()
                        self.assertTrue(info.dead)
                        self.assertEqual(info.returncode, returncode)
                        callback.assert_not_called()
                        idle_add.assert_called_once_with(callback, proc)
                        if not enabled:
                            self.assertFalse(select([proc.stdout], [], [], .05)[0], "descendant exited with cleanup disabled")
                            os.kill(descendant, signal.SIGTERM)
                        self.assertEqual(read_line(), b"terminated\n")
                        self.assertEqual(read_line(), b"")
                        descendant_done = True
                    finally:
                        if descendant and not descendant_done:
                            try:
                                os.kill(descendant, signal.SIGKILL)
                            except ProcessLookupError:
                                pass
                        if proc.poll() is None:
                            proc.kill()
                        proc.wait(timeout=5)
                        proc.stdin.close()
                        proc.stdout.close()


def main():
    unittest.main()


if __name__ == '__main__':
    main()
