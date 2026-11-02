#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import sys
import time
import unittest
from select import select
from subprocess import DEVNULL, TimeoutExpired
from threading import Thread
from unittest.mock import patch

from xpra.net.ssh import exec_client
from xpra.os_util import POSIX
from xpra.util import child_reaper


@unittest.skipUnless(POSIX, "requires POSIX signals and inherited pipe descriptors")
class SSHExecClientTest(unittest.TestCase):
    def connect(self, exit_ssh=True, ignore_sigterm=False):
        release_read, release_write = os.pipe()
        self.addCleanup(os.close, release_write)
        command = (
            "import os, signal\n"
            "def exit_on_term(*args):\n"
            f"    os.read({release_read}, 1)\n"
            "    raise SystemExit(7)\n"
            f"signal.signal(signal.SIGTERM, {'signal.SIG_IGN' if ignore_sigterm else 'exit_on_term'})\n"
            "print('ready', flush=True)\n"
            + (f"os.read({release_read}, 1)\nraise SystemExit(7)\n" if ignore_sigterm else "signal.pause()\n")
        )
        try:
            with patch.object(exec_client, "get_ssh_kwargs", return_value={"stderr": DEVNULL, "pass_fds": (release_read,)}):
                conn = exec_client.connect_to({
                    "full_ssh": [sys.executable, "-c", command],
                    "remote_xpra": ["xpra"], "proxy_command": ["_proxy"], "display_as_args": [],
                    "host": "fixture", "exit_ssh": exit_ssh, "env": os.environ.copy(),
                })
        finally:
            os.close(release_read)
        child = conn.process[0]
        with patch.object(child_reaper.GLib, "timeout_add"):
            reaper = child_reaper.ChildReaper()
        # XpraClientBase.make_protocol registers the transport's Popen this way.
        process, name, command = conn.process
        info = reaper.add_process(process, name, command, ignore=True, forget=False)

        def cleanup():
            try:
                os.write(release_write, b"x")
            except BrokenPipeError:
                pass
            conn.close()
            try:
                child.wait(timeout=3)
            except TimeoutExpired:
                child.kill()
                child.wait(timeout=3)
        self.addCleanup(cleanup)
        self.assertTrue(select((child.stdout,), (), (), 3)[0], "child did not become ready")
        self.assertEqual(child.stdout.readline(), b"ready\n")
        return conn, child, release_write, reaper, info

    def close(self, conn):
        errors = []

        def close():
            try:
                conn.close()
                conn.close()
            except Exception as exc:
                errors.append(exc)

        with patch.object(exec_client, "start_thread") as start:
            closer = Thread(target=close, daemon=True)
            closer.start()
            closer.join(3)
            self.assertFalse(closer.is_alive(), "close blocked waiting for SSH to exit")
            start.assert_not_called()
        self.assertEqual(errors, [])

    def test_owned_tunnel_reaped_by_normal_polling(self):
        for ignore_sigterm in (False, True):
            with self.subTest(ignore_sigterm=ignore_sigterm):
                conn, child, release, reaper, info = self.connect(ignore_sigterm=ignore_sigterm)
                with patch.object(child, "kill") as kill:
                    self.close(conn)
                    reaper.poll()
                    self.assertFalse(info.dead)
                    self.assertIsNone(child.returncode)
                    os.write(release, b"x")
                    deadline = time.monotonic() + 3
                    while not info.dead and time.monotonic() < deadline:
                        reaper.poll()
                        time.sleep(0.01)
                    self.assertTrue(info.dead, "SSH was not reaped")
                    self.assertEqual(info.returncode, 7)
                    self.assertEqual(child.returncode, 7)
                    self.assertRaises(ChildProcessError, os.waitpid, child.pid, os.WNOHANG)
                    kill.assert_not_called()

    def test_shared_tunnel_is_left_running(self):
        conn, child, _release, reaper, info = self.connect(exit_ssh=False, ignore_sigterm=True)
        with patch.object(child, "terminate") as terminate:
            self.close(conn)
            reaper.poll()
            self.assertFalse(info.dead)
            self.assertIsNone(child.returncode)
            terminate.assert_not_called()

    def test_already_exited_tunnel(self):
        conn, child, release, reaper, info = self.connect(ignore_sigterm=True)
        os.write(release, b"x")
        self.assertEqual(child.wait(timeout=3), 7)
        with patch.object(child, "terminate") as terminate:
            self.close(conn)
            reaper.poll()
            self.assertTrue(info.dead)
            self.assertEqual(info.returncode, 7)
            self.assertEqual(child.returncode, 7)
            terminate.assert_not_called()


if __name__ == "__main__":
    unittest.main()
