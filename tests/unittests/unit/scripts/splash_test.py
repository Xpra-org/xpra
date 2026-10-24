#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import signal
import unittest
from io import BytesIO
from unittest.mock import Mock, patch

from xpra.scripts.splash import make_progress_process


class SplashTest(unittest.TestCase):

    def test_splash_preserves_saved_display_environment(self):
        for backend in ("", "wayland", "x11", "wayland,x11"):
            saved_env = {"DISPLAY": ":0", "WAYLAND_DISPLAY": "wayland-1", "XDG_SESSION_TYPE": "x11"}
            if backend:
                saved_env["GDK_BACKEND"] = backend
            process = Mock()
            process.poll.return_value = None
            with self.subTest(backend=backend), \
                 patch.dict(os.environ, {"DISPLAY": ":100", "WAYLAND_DISPLAY": "wayland-100", "GDK_BACKEND": "x11"}, clear=True), \
                 patch("xpra.scripts.splash.get_saved_env", return_value=saved_env), \
                 patch("xpra.scripts.splash.Popen", return_value=process) as popen, \
                 patch("xpra.util.child_reaper.get_child_reaper"), patch("xpra.scripts.splash.SPLASH_KEEPALIVE_INTERVAL", 0):
                self.assertIs(make_progress_process("test"), process)
                splash_env = popen.call_args.kwargs["env"]
                self.assertEqual(splash_env["DISPLAY"], ":0")
                self.assertEqual(splash_env["WAYLAND_DISPLAY"], "wayland-1")
                self.assertEqual(splash_env.get("GDK_BACKEND", ""), backend)
                self.assertEqual(os.environ["DISPLAY"], ":100")
                self.assertEqual(os.environ["GDK_BACKEND"], "x11")

    def test_splash_keepalive_sender(self):
        class ProgressProcess:
            def __init__(self):
                self.stdin = BytesIO()
                self.returncode = None

            def poll(self):
                return self.returncode

            def terminate(self):
                self.returncode = -signal.SIGTERM

        class StopEvent:
            def __init__(self):
                self.stopped = False
                self.wait_delays = []

            def set(self):
                self.stopped = True

            def is_set(self):
                return self.stopped

            def wait(self, delay):
                self.wait_delays.append(delay)
                return len(self.wait_delays) >= 2

        process = ProgressProcess()
        stop_event = StopEvent()
        keepalive_threads = []

        def capture_thread(target, name, daemon=False, args=()):
            keepalive_threads.append((target, name, daemon, args))
            return Mock()

        with patch("xpra.scripts.splash.Popen", return_value=process), \
             patch("xpra.util.child_reaper.get_child_reaper"), \
             patch("xpra.scripts.splash.SPLASH_KEEPALIVE_INTERVAL", 1), \
             patch("threading.Event", return_value=stop_event), \
             patch("xpra.util.thread.start_thread", side_effect=capture_thread):
            assert make_progress_process("test") is process
            assert len(keepalive_threads) == 1
            target, name, daemon, args = keepalive_threads[0]
            assert name == "splash-keepalive"
            assert daemon is True
            assert not args
            target()
            data = process.stdin.getvalue()
            assert data.count(b"keepalive\n") == 2
            assert stop_event.wait_delays == [1, 1]
            process.terminate()
            assert stop_event.stopped


def main():
    unittest.main()


if __name__ == '__main__':
    main()
