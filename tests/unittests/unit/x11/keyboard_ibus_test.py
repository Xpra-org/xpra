#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import shlex
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from contextlib import ExitStack
from itertools import product
from pathlib import Path
from select import select
from textwrap import dedent
from types import SimpleNamespace
from unittest.mock import Mock, patch

from xpra.os_util import POSIX
from xpra.util import child_reaper
from xpra.util.child_reaper import ChildReaper


class TestIBusStart(unittest.TestCase):

    def test_get_ibus_dirs(self):
        from xpra.x11.subsystem.keyboard import get_ibus_dirs
        with tempfile.TemporaryDirectory() as tmpdir:
            config = os.path.join(tmpdir, "config")
            cache = os.path.join(tmpdir, "cache")
            with patch.dict(os.environ, {"XDG_CONFIG_HOME": config, "XDG_CACHE_HOME": cache}):
                dirs = get_ibus_dirs()
            self.assertEqual(dirs, (os.path.join(config, "ibus", "bus"), os.path.join(cache, "ibus")))
            for path in dirs:
                assert os.path.isdir(path)

    def test_may_start_ibus(self):
        from xpra.x11.subsystem import keyboard
        scheduler = Mock()
        with tempfile.TemporaryDirectory() as tmpdir, \
                patch.dict(os.environ, {"XPRA_SESSION_DIR": tmpdir}), \
                patch.object(keyboard, "find_libexec_command", return_value=""), \
                patch.object(keyboard, "Popen", return_value=Mock(pid=12345)) as popen, \
                patch.object(keyboard, "get_child_reaper"):
            keyboard.may_start_ibus({}, scheduler)
        # started immediately, not from the main loop: the server may be confined by then
        popen.assert_called_once()
        scheduler.idle_add.assert_not_called()

    def test_daemonizer_pidfile_not_ready(self):
        from xpra.x11.subsystem import keyboard
        scheduler = Mock()
        launcher = Mock(pid=12345)
        launcher.poll.return_value = 0
        with tempfile.TemporaryDirectory() as tmpdir, \
                patch.dict(os.environ, {"XPRA_SESSION_DIR": tmpdir}), \
                patch.object(keyboard, "find_libexec_command", return_value="/daemonizer"), \
                patch.object(keyboard, "KILL_CHILD_PROCESS_GROUP", True), \
                patch.object(keyboard, "Popen", return_value=launcher), \
                patch.object(keyboard.os, "killpg"), \
                patch.object(keyboard.os, "getpgrp", return_value=1), \
                patch.object(keyboard, "get_child_reaper") as reaper:
            reaper.return_value.add_pid.return_value.dead = False
            keyboard.may_start_ibus({}, scheduler)
            poll_daemonizer = scheduler.timeout_add.call_args.args[1]
            # The original launcher has exited, but the detached process is still starting.
            self.assertTrue(poll_daemonizer())
            reaper.return_value.add_pid.assert_not_called()
            Path(tmpdir, "ibus-daemon.pid").write_text("12345\n", encoding="utf8")
            self.assertFalse(poll_daemonizer())
            self.assertTrue(reaper.return_value.add_pid.call_args.kwargs["kill_process_group"])
            self.assertEqual(scheduler.timeout_add.call_args.args[0], 1000)

    @unittest.skipUnless(POSIX, "requires POSIX process groups")
    def test_process_group_detection(self):
        from xpra.x11.subsystem import keyboard
        with patch.object(keyboard, "KILL_CHILD_PROCESS_GROUP", True):
            for pid in (-1, 0, 1, os.getpgrp()):
                with self.subTest(pid=pid):
                    self.assertFalse(keyboard.ibus_has_process_group(pid))
            command = [sys.executable, "-c", "import sys; sys.stdin.buffer.read(1)"]
            with subprocess.Popen(command, stdin=subprocess.PIPE, start_new_session=True) as proc:
                # OpenBSD forbids querying the group of this separate session.
                with patch.object(keyboard.os, "getpgid", side_effect=PermissionError):
                    self.assertTrue(keyboard.ibus_has_process_group(proc.pid))
                with patch.object(keyboard, "KILL_CHILD_PROCESS_GROUP", False):
                    self.assertFalse(keyboard.ibus_has_process_group(proc.pid))
            self.assertFalse(keyboard.ibus_has_process_group(proc.pid))

    @staticmethod
    def make_manager(input_method="ibus"):
        from xpra.x11.subsystem import keyboard
        manager = keyboard.X11KeyboardManager.__new__(keyboard.X11KeyboardManager)
        manager.input_method = input_method
        manager.server = SimpleNamespace(get_child_env=dict)
        return manager

    def test_early_setup(self):
        from xpra.x11.subsystem import keyboard
        manager = self.make_manager()
        with patch.object(keyboard, "configure_imsettings_env", return_value="ibus"), \
                patch.object(keyboard, "IBUS", True), \
                patch.object(keyboard, "may_start_ibus") as may_start_ibus:
            manager.early_setup()
        may_start_ibus.assert_called_once_with({}, manager)

    def test_landlock_paths(self):
        from xpra.x11.subsystem import keyboard
        self.assertEqual(self.make_manager("xim").get_landlock_paths(), {})
        dirs = ("/home/user/.config/ibus/bus", "/home/user/.cache/ibus")
        with patch.object(keyboard, "get_ibus_dirs", return_value=dirs):
            paths = self.make_manager().get_landlock_paths()
        self.assertEqual(paths, {"read": (dirs[0], ), "socket": (dirs[1], )})


@unittest.skipUnless(POSIX, "requires POSIX process groups and fork")
class TestIBusProcessGroup(unittest.TestCase):

    def setUp(self):
        previous = signal.signal(signal.SIGCHLD, signal.SIG_DFL)
        self.addCleanup(signal.signal, signal.SIGCHLD, previous)

    def test_daemon_descendants(self):
        from xpra.x11.subsystem import keyboard

        daemonizer_path = str(Path(__file__).resolve().parents[4] / "fs/libexec/xpra/daemonizer")
        script = dedent("""\
            import os, signal, sys
            leader = os.getpid()
            if os.fork() == 0:
                def terminated(*args):
                    os.write(1, b'terminated\\n')
                    os._exit(0)
                signal.signal(signal.SIGTERM, terminated)
                pgid = os.getpgrp()
                # OpenBSD cannot report the SID after the daemonizer's session leader exits.
                sid = os.getsid(0) if pgid == leader else 0
                print(leader, os.getpid(), pgid, sid, flush=True)
                while True:
                    signal.pause()
            sys.stdin.buffer.read(1)
            sys.exit(7)
            """)
        real_popen = subprocess.Popen
        for daemonized, enabled, action in product((False, True), (False, True), ("exit", "kill", "stop", "upgrade")):
            with self.subTest(daemonized=daemonized, enabled=enabled, action=action), ExitStack() as stack:
                tmpdir = stack.enter_context(tempfile.TemporaryDirectory())
                stack.enter_context(patch.dict(os.environ, {"XPRA_SESSION_DIR": tmpdir}))
                stack.enter_context(patch.object(child_reaper.GLib, "timeout_add"))
                stack.enter_context(patch.object(child_reaper.GLib, "idle_add"))
                reaper = ChildReaper()
                stack.enter_context(patch.object(child_reaper, "singleton", reaper))
                stack.enter_context(patch.object(keyboard, "KILL_CHILD_PROCESS_GROUP", enabled))
                stack.enter_context(patch.object(keyboard, "IBUS", True))
                stack.enter_context(patch.object(keyboard, "configure_imsettings_env", return_value="ibus"))
                stack.enter_context(patch.object(keyboard, "find_libexec_command", return_value=daemonizer_path if daemonized else ""))
                stack.enter_context(patch("xpra.platform.paths.get_python_execfile_command", return_value=[sys.executable]))
                stack.enter_context(patch.object(keyboard, "IBUS_DAEMON_COMMAND", shlex.join([sys.executable, "-c", script])))
                launchers = []

                def popen(command, **kwargs):
                    proc = real_popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, bufsize=0, **kwargs)
                    launchers.append(proc)
                    return proc

                stack.enter_context(patch.object(keyboard, "Popen", side_effect=popen))
                timers = []
                server = Mock()
                server.get_child_env.return_value = os.environ.copy()
                server.timeout_add.side_effect = lambda delay, callback, *args: timers.append((delay, callback, args))
                manager = keyboard.X11KeyboardManager(server)
                manager.input_method = "ibus"
                manager.early_setup()
                self.assertEqual(len(launchers), 1)
                launcher = launchers[0]
                leader = descendant = 0
                leader_done = descendant_done = False

                def read_line():
                    self.assertTrue(select([launcher.stdout], [], [], 5)[0], "timed out waiting for ibus descendant output")
                    return launcher.stdout.readline()

                def wait_for(predicate):
                    deadline = time.monotonic() + 5
                    while not predicate():
                        self.assertLess(time.monotonic(), deadline, "timed out waiting for ibus state")
                        time.sleep(.01)

                def run_startup_timers():
                    for timer in tuple(timers):
                        delay, callback, args = timer
                        if delay == 50:
                            timers.remove(timer)
                            if callback(*args):
                                timers.append(timer)
                    return reaper.get_proc_info(leader) is not None

                try:
                    leader, descendant, pgid, sid = map(int, read_line().split())
                    if enabled:
                        self.assertEqual(pgid, leader)
                        self.assertEqual(sid, leader)
                    else:
                        self.assertNotEqual(pgid, leader)
                    if daemonized:
                        self.assertEqual(launcher.wait(timeout=5), 0)
                        wait_for(run_startup_timers)
                        # Exiting the initial launcher must leave the daemon running.
                        os.kill(leader, 0)
                    else:
                        self.assertEqual(leader, launcher.pid)
                    info = reaper.get_proc_info(leader)
                    self.assertIsNotNone(info)
                    self.assertEqual(info.kill_process_group, enabled)
                    if action == "upgrade":
                        manager.late_cleanup(stop=False)
                        os.kill(leader, 0)
                        timers.clear()
                        reaper = ChildReaper()
                        child_reaper.singleton = reaper
                        # New servers enable the feature even when adopting an older,
                        # non-isolated daemon; only isolated groups should be signalled.
                        stack.enter_context(patch.object(keyboard, "KILL_CHILD_PROCESS_GROUP", True))
                        manager = keyboard.X11KeyboardManager(server)
                        manager.input_method = "ibus"
                        manager.early_setup()
                        self.assertEqual(len(launchers), 1)
                        info = reaper.get_proc_info(leader)
                        self.assertEqual(info.kill_process_group, enabled)
                    if action == "exit":
                        launcher.stdin.write(b"x")
                    elif action == "kill":
                        os.kill(leader, signal.SIGKILL)
                    else:
                        manager.late_cleanup()
                    if daemonized:
                        wait_for(lambda: not os.path.exists(keyboard.ibus_pid_file()))
                        # The daemonizer must clean up without any server reaper pass.
                    else:
                        launcher.wait(timeout=5)
                        if action in ("exit", "kill"):
                            reaper.poll()
                    leader_done = True
                    if not enabled:
                        self.assertFalse(select([launcher.stdout], [], [], .05)[0], "descendant exited with cleanup disabled")
                        os.kill(descendant, signal.SIGTERM)
                    self.assertEqual(read_line(), b"terminated\n")
                    self.assertEqual(read_line(), b"")
                    descendant_done = True
                    for delay, callback, args in timers:
                        if delay == 1000:
                            self.assertFalse(callback(*args))
                    reaper.poll()
                    self.assertTrue(info.dead)
                finally:
                    for pid in (descendant if not descendant_done else 0, leader if not leader_done else 0):
                        if pid:
                            try:
                                os.kill(pid, signal.SIGKILL)
                            except ProcessLookupError:
                                pass
                    if launcher.poll() is None:
                        launcher.kill()
                    launcher.wait(timeout=5)
                    launcher.stdin.close()
                    launcher.stdout.close()


def main():
    from xpra.os_util import POSIX, OSX
    if POSIX and not OSX:
        unittest.main()


if __name__ == "__main__":
    main()
