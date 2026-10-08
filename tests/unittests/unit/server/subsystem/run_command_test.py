#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import signal
import subprocess
import sys
import tempfile
import unittest
from time import monotonic, sleep
from types import SimpleNamespace
from unittest.mock import Mock, patch

from xpra.os_util import POSIX, gi_import
from xpra.util.child_reaper import ChildReaper
from xpra.util.objects import typedict
from xpra.server.command_output import OUTPUT_LIMIT, pipe_reader
from xpra.server.subsystem.command import ChildCommandServer
from xpra.net.common import is_request_allowed

GLib = gi_import("GLib")


class Protocol:
    def __init__(self):
        self.closed = False
        self.packets = []

    def is_closed(self):
        return self.closed

    def send_now(self, packet):
        self.packets.append(packet)

    def response(self):
        return self.packets[0][1]["run_response"]


class RunCommandTest(unittest.TestCase):
    def setUp(self):
        with patch("xpra.util.child_reaper.GLib.timeout_add"):
            self.reaper = ChildReaper()
        self.addCleanup(patch.stopall)
        patch("xpra.util.child_reaper.singleton", self.reaper).start()
        self.processes = []

        def spawn(*args, **kwargs):
            proc = subprocess.Popen(*args, **kwargs)
            self.processes.append(proc)
            return proc

        patch("xpra.server.subsystem.command.Popen", side_effect=spawn).start()
        server = SimpleNamespace(
            connect=Mock(), get_child_env=lambda: os.environ.copy(),
            get_server_source=lambda proto: None, session_name="test",
            cancel_verify_connection_accepted=Mock(),
            idle_add=GLib.idle_add, timeout_add=GLib.timeout_add, source_remove=GLib.source_remove,
        )
        self.command = ChildCommandServer(server)

    def tearDown(self):
        self.command.cleanup()
        for proc in self.processes:
            if proc.poll() is None:
                proc.terminate()
            proc.wait(timeout=5)
        self.pump(lambda: all(not proc.stdout or proc.stdout.closed for proc in self.processes))

    def pump(self, condition, timeout=5):
        deadline = monotonic() + timeout
        context = GLib.MainContext.default()
        while monotonic() < deadline:
            self.reaper.poll()
            for _ in range(50):
                if not context.pending():
                    break
                context.iteration(False)
            if condition():
                return
            sleep(0.001)
        self.fail("command request did not complete before the test deadline")

    def run_command(self, script, wait=1000, request="run"):
        proto = Protocol()
        caps = typedict({"run": (sys.executable, "-c", script), "run-wait-time": wait})
        handler = getattr(self.command, f"_handle_hello_request_{request}")
        self.assertTrue(handler(proto, caps))
        return proto

    def test_completion_and_binary_output(self):
        proto = self.run_command("import os; os.write(1, b'out\\x00\\xff'); os.write(2, b'err\\x00'); raise SystemExit(7)")
        self.pump(lambda: bool(proto.packets))
        response = proto.response()
        self.assertEqual(response["stdout"], b"out\x00\xff")
        self.assertEqual(response["stderr"], b"err\x00")
        self.assertEqual(response["returncode"], 7)
        self.assertGreater(response["pid"], 0)
        self.assertFalse(response["stdout-truncated"])
        self.assertFalse(response["stderr-truncated"])
        self.assertEqual(len(proto.packets), 1)
        self.pump(lambda: not self.command._run_requests)

    def test_large_output_and_truncation(self):
        size = OUTPUT_LIMIT * 2 + 65536
        proto = self.run_command(
            f"import os; chunk=b'x'*65536\nfor i in range({size // 65536}): os.write(1, chunk); os.write(2, chunk)",
            wait=5000,
        )
        self.pump(lambda: bool(proto.packets))
        response = proto.response()
        self.assertEqual(response["returncode"], 0)
        for stream in ("stdout", "stderr"):
            self.assertEqual(response[stream], b"x" * OUTPUT_LIMIT)
            self.assertTrue(response[f"{stream}-truncated"])

    def test_timeout_keeps_draining(self):
        with tempfile.TemporaryDirectory() as directory:
            marker = os.path.join(directory, "done")
            proto = self.run_command(
                "import os, time; os.write(1, b'early'); time.sleep(.3); "
                f"os.write(1, b'x'*3000000); os.write(2, b'y'*3000000); open({marker!r}, 'w').close()",
                wait=150,
            )
            self.pump(lambda: bool(proto.packets))
            self.assertEqual(proto.response()["stdout"], b"early")
            self.assertNotIn("returncode", proto.response())
            self.assertFalse(os.path.exists(marker))
            self.pump(lambda: not self.command._run_requests)
            self.assertTrue(os.path.exists(marker))
            self.assertEqual(len(proto.packets), 1)

    def test_disconnect_and_shutdown(self):
        proto = self.run_command("import time, os; time.sleep(.1); os.write(1, b'x'*2000000)")
        proto.closed = True
        self.command.cleanup_protocol(proto)
        self.pump(lambda: not self.command._run_requests)
        self.assertFalse(proto.packets)
        proto = self.run_command("import time; time.sleep(5)")
        self.command.cleanup()
        self.pump(lambda: self.processes[-1].stdout.closed)
        self.assertFalse(proto.packets)

    def test_zero_wait_and_exec(self):
        for request, wait in (("run", 0), ("run", -1), ("run", "invalid"), ("exec", 5000)):
            proto = self.run_command("import time; time.sleep(.1)", wait, request)
            self.assertEqual(set(proto.response()), {"pid"})
            self.assertIsNone(self.processes[-1].stdout)
            self.assertIsNone(self.processes[-1].stderr)

    def test_errors(self):
        for caps, code in (({}, 27), ({"run": ("/nonexistent/xpra-command",), "run-wait-time": 5000}, 31)):
            proto = Protocol()
            self.command._handle_hello_request_run(proto, typedict(caps))
            self.assertEqual(proto.response()["code"], code)
            self.assertFalse(self.command._run_requests)

    def test_concurrent_requests(self):
        protocols = [self.run_command(f"import time; time.sleep(.05); print({i})") for i in range(5)]
        self.pump(lambda: all(proto.packets for proto in protocols))
        for i, proto in enumerate(protocols):
            self.assertEqual(proto.response()["stdout"], f"{i}\n".encode())
            self.assertEqual(len(proto.packets), 1)

    def test_exit_deadline_race(self):
        for _ in range(10):
            proto = self.run_command("print('done')", wait=20)
            self.pump(lambda: bool(proto.packets))
            self.pump(lambda: not self.command._run_requests)
            self.assertEqual(len(proto.packets), 1)

    @unittest.skipUnless(POSIX, "requires POSIX signals and fork")
    def test_signal_and_inherited_pipes(self):
        proto = self.run_command("import os, signal; os.kill(os.getpid(), signal.SIGTERM)")
        self.pump(lambda: bool(proto.packets))
        self.assertEqual(proto.response()["returncode"], -signal.SIGTERM)
        proto = self.run_command("import os, time; pid=os.fork()\nif pid==0: time.sleep(.5); os._exit(0)\nos.write(1, b'parent')", wait=2000)
        start = monotonic()
        self.pump(lambda: bool(proto.packets))
        self.assertLess(monotonic() - start, .5)
        self.assertEqual(proto.response()["stdout"], b"parent")
        self.assertEqual(proto.response()["returncode"], 0)

    def test_exec_authorization(self):
        for options, allowed in (({}, True), ({"run": "no"}, False), ({"exec": "no"}, False),
                                 ({"run": "no", "exec": "yes"}, False), ({"exec": "yes"}, True)):
            proto = SimpleNamespace(_conn=SimpleNamespace(options=options))
            self.assertEqual(is_request_allowed(proto, "exec"), allowed)

    def test_windows_pipe_reader(self):
        available = [None, 3, "eof", "error"]

        def peek(_handle, _buffer, _size, _read, pending, _left):
            value = available.pop(0)
            if isinstance(value, int):
                pending._obj.value = value
            return value not in ("eof", "error")

        peek_function = Mock(side_effect=peek)
        common = SimpleNamespace(kernel32=SimpleNamespace(PeekNamedPipe=peek_function),
                                 ERROR_BROKEN_PIPE=109, ERROR_PIPE_NOT_CONNECTED=233)
        with patch("xpra.server.command_output.WIN32", True), \
             patch.dict(sys.modules, {"msvcrt": SimpleNamespace(get_osfhandle=lambda fd: fd),
                                      "xpra.platform.win32.common": common}), \
             patch("ctypes.WinError", side_effect=lambda error: OSError(error), create=True), \
             patch("ctypes.get_last_error", side_effect=[109, 5], create=True), \
             patch("os.read", return_value=b"abc") as read:
            reader = pipe_reader(SimpleNamespace(fileno=lambda: 42))
            self.assertIsNone(reader())
            read.assert_not_called()
            self.assertEqual(reader(), b"abc")
            read.assert_called_once_with(42, 3)
            self.assertEqual(reader(), b"")
            with self.assertRaises(OSError):
                reader()


if __name__ == "__main__":
    unittest.main()
