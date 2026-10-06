#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import sys
import tempfile
import unittest
from subprocess import PIPE
from time import monotonic, sleep

import xpra
from xpra.os_util import POSIX
from unit.process_test_util import ProcessTestUtil

ROOT = os.path.dirname(os.path.dirname(xpra.__file__))


@unittest.skipUnless(POSIX, "uses Unix domain sockets")
class RunnerServerTest(ProcessTestUtil):
    def wait_for(self, condition, server, timeout=10):
        deadline = monotonic() + timeout
        while monotonic() < deadline:
            if condition():
                return
            if server.poll() is not None:
                self.show_proc_error(server, "runner server exited unexpectedly")
            sleep(.01)
        self.show_proc_error(server, "runner test timed out")

    def test_command_results(self):
        for compatible in (False, True):
            with self.subTest(compatible=compatible), tempfile.TemporaryDirectory(prefix="xpra-run-") as directory:
                env = self.get_default_run_env()
                env.update({
                    "PYTHONPATH": ROOT, "XPRA_BACKWARDS_COMPATIBLE": str(int(compatible)),
                    "XPRA_USE_PROCESS_POLLING": str(int(compatible)),
                })
                command = self.get_xpra_cmd()
                sockpath = os.path.join(directory, "runner.sock")
                server = self.run_command(command + [
                    "runner", f"--bind={sockpath}", f"--socket-dirs={directory}",
                    "--daemon=no", "--systemd-run=no", "--mdns=no",
                ], env=env, cwd=directory)
                try:
                    self.wait_for(lambda: os.path.exists(sockpath), server)

                    def invoke(mode, script, wait=5000):
                        client_env = dict(env, XPRA_RUN_WAIT_TIME=str(wait))
                        client = self.run_command(command + [
                            mode, f"socket://{sockpath}", "--", sys.executable, "-c", script,
                        ], stdout=PIPE, stderr=PIPE, env=client_env, cwd=directory)
                        output, errors = client.communicate(timeout=15)
                        return client.returncode, output, errors

                    status, output, errors = invoke(
                        "run", "import os; os.write(1, b'x'*32768+b'\\x00\\xff'); "
                        "os.write(2, b'remote error'); raise SystemExit(7)",
                    )
                    self.assertEqual(status, 7, errors)
                    self.assertEqual(output, b"x" * 32768 + b"\x00\xff")
                    self.assertIn(b"remote error", errors)
                    self.assertIn(b"command started with pid ", errors)

                    marker = os.path.join(directory, "drained")
                    status, output, errors = invoke(
                        "run", "import os, time; os.write(1, b'early'); time.sleep(.5); "
                        "os.write(1, b'x'*3000000); os.write(2, b'y'*3000000); "
                        f"open({marker!r}, 'w').close()", wait=200,
                    )
                    self.assertEqual(status, 0, errors)
                    self.assertEqual(output, b"early")
                    self.wait_for(lambda: os.path.exists(marker), server)

                    marker = os.path.join(directory, "exec-done")
                    status, output, errors = invoke("exec", f"import time; time.sleep(1); open({marker!r}, 'w').close()")
                    self.assertEqual(status, 0, errors)
                    self.assertRegex(output, rb"^command started with pid [0-9]+\n$")
                    self.assertFalse(os.path.exists(marker), "exec waited for the command")
                    self.wait_for(lambda: os.path.exists(marker), server)
                finally:
                    if server.poll() is None:
                        server.terminate()
                    server.wait(timeout=10)


if __name__ == "__main__":
    unittest.main()
