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
import unittest
from contextlib import ExitStack
from itertools import product
from select import select
from textwrap import dedent
from unittest.mock import Mock, patch

from xpra.os_util import POSIX
from xpra.util import child_reaper
from xpra.util.child_reaper import ChildReaper

from unit.test_util import silence_info


@unittest.skipUnless(POSIX, "requires POSIX process groups and fork")
class HelperProcessGroupTest(unittest.TestCase):

    def setUp(self):
        previous = signal.signal(signal.SIGCHLD, signal.SIG_DFL)
        self.addCleanup(signal.signal, signal.SIGCHLD, previous)

    def test_helper_descendants(self):
        from xpra.net import subprocess_wrapper
        from xpra.server.subsystem import pulseaudio, webcam

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
            sys.exit(7)
            """)
        real_popen = subprocess.Popen
        for kind, enabled, action in product(("pulseaudio", "audio", "webcam"), (False, True), ("exit", "kill", "stop")):
            with self.subTest(kind=kind, enabled=enabled, action=action), ExitStack() as stack:
                stack.enter_context(patch.object(child_reaper.GLib, "timeout_add"))
                idle_add = stack.enter_context(patch.object(child_reaper.GLib, "idle_add"))
                reaper = ChildReaper()
                stack.enter_context(patch.object(child_reaper, "singleton", reaper))
                processes = []

                def popen(command, **kwargs):
                    if command == ["pactl", "exit"]:
                        # Emulate a successful graceful shutdown request.
                        processes[0].terminate()
                        proc = Mock(pid=12345)
                        proc.poll.return_value = 0
                        return proc
                    kwargs.setdefault("stdin", subprocess.PIPE)
                    kwargs.setdefault("stdout", subprocess.PIPE)
                    kwargs["bufsize"] = 0
                    proc = real_popen(command, **kwargs)
                    processes.append(proc)
                    return proc

                env = os.environ.copy()
                server = Mock()
                server.get_child_env.return_value = env
                server.subsystems = {}
                command = [sys.executable, "-c", script]
                if kind == "pulseaudio":
                    module = pulseaudio
                    stack.enter_context(patch.object(module, "Popen", side_effect=popen))
                    stack.enter_context(patch.object(module, "load_pid", return_value=0))
                    stack.enter_context(patch.object(module, "pollwait", return_value=0))
                    stack.enter_context(patch.object(module.PulseaudioServer, "configure_pulse_dirs"))
                    stack.enter_context(patch.object(module.PulseaudioServer, "get_pulseaudio_server_env", return_value=env))
                    helper = module.PulseaudioServer(server)
                    helper.command = shlex.join(command)
                    start = helper.do_init_pulseaudio
                    stop = helper.cleanup_pulseaudio
                elif kind == "audio":
                    module = subprocess_wrapper
                    stack.enter_context(patch.object(module.subprocess, "Popen", side_effect=popen))
                    helper = module.SubprocessCaller("test audio")
                    helper.command = command

                    def start():
                        helper.process = helper.exec_subprocess()

                    stop = helper.stop_process
                else:
                    module = webcam
                    stack.enter_context(patch.object(module, "Popen", side_effect=popen))
                    stack.enter_context(patch("xpra.platform.paths.get_xpra_command", return_value=command))
                    server.subsystems["network"] = Mock(unix_socket_paths=["/unused-xpra-test-socket"])
                    helper = module.WebcamServer(server)

                    def start():
                        helper._spawn_webcam_client(Mock(), 0, 640, 480)

                    stop = helper.cleanup
                stack.enter_context(patch.object(module, "KILL_CHILD_PROCESS_GROUP", enabled))
                stack.enter_context(silence_info(module))
                start()
                self.assertEqual(len(processes), 1)
                proc = processes[0]
                descendant = 0
                descendant_done = False

                def read_line():
                    self.assertTrue(select([proc.stdout], [], [], 5)[0], "timed out waiting for descendant output")
                    return proc.stdout.readline()

                try:
                    descendant, pgid, sid = map(int, read_line().split())
                    isolated = enabled or kind == "audio"
                    self.assertEqual(pgid, proc.pid if isolated else os.getpgrp())
                    self.assertEqual(sid, proc.pid if isolated else os.getsid(0))
                    info = reaper.get_proc_info(proc.pid)
                    self.assertEqual(info.kill_process_group, enabled)
                    if action == "exit":
                        proc.stdin.write(b"x")
                        returncode = 7
                    elif action == "kill":
                        proc.kill()
                        returncode = -signal.SIGKILL
                    else:
                        stop()
                        returncode = -signal.SIGTERM
                    self.assertEqual(proc.wait(timeout=5), returncode)
                    if action == "exit":
                        reaper.cleanup()
                    elif action == "kill":
                        reaper.poll()
                    # Explicit shutdown must work without another reaper pass.
                    if not enabled:
                        self.assertFalse(select([proc.stdout], [], [], .05)[0], "descendant exited with cleanup disabled")
                        os.kill(descendant, signal.SIGTERM)
                    self.assertEqual(read_line(), b"terminated\n")
                    self.assertEqual(read_line(), b"")
                    descendant_done = True
                    if action != "stop":
                        self.assertTrue(info.dead)
                        self.assertEqual(info.returncode, returncode)
                        idle_add.assert_called_once()
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


if __name__ == "__main__":
    unittest.main()
