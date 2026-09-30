#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import time
import unittest
import threading

from xpra.os_util import gi_import
from xpra.util.ui_thread_watcher import UIThreadWatcher

GLib = gi_import("GLib")

POLLING = 50
MAX_DELTA = 200


class UIThreadWatcherTest(unittest.TestCase):

    def setUp(self):
        self.events: list[tuple[str, str]] = []
        self.watcher = UIThreadWatcher(POLLING, MAX_DELTA, 0)
        self.loop = GLib.MainLoop()

    def tearDown(self):
        self.watcher.stop()

    def record(self, event: str) -> None:
        self.events.append((event, threading.current_thread().name))

    def stall_ui_thread(self, stall: float, run_for: float) -> None:
        def stall_now() -> bool:
            self.record("stall")
            time.sleep(stall)
            return False

        # give the watcher time to see the UI thread running first:
        GLib.timeout_add(300, stall_now)
        GLib.timeout_add(int(run_for * 1000), self.loop.quit)
        self.watcher.start()
        self.loop.run()

    def test_stall(self):
        self.watcher.add_fail_callback(lambda: self.record("fail"))
        self.watcher.add_resume_callback(lambda: self.record("resume"))
        self.stall_ui_thread(0.5, 1.5)
        self.assertEqual([event for event, _ in self.events],
                         ["stall", "fail", "resume"])
        threads = dict(self.events)
        self.assertEqual(threads["resume"], threading.main_thread().name,
                         "resume callbacks must run from the UI thread")
        self.assertNotEqual(threads["fail"], threading.main_thread().name,
                            "fail callbacks run from the polling thread")

    def test_no_stall(self):
        self.watcher.add_fail_callback(lambda: self.record("fail"))
        self.watcher.add_resume_callback(lambda: self.record("resume"))
        self.stall_ui_thread(0.05, 1)
        self.assertEqual([event for event, _ in self.events], ["stall"])

    def test_resume_waits_for_fail_callbacks(self):
        # the UI thread wakes up whilst the fail callbacks are still running,
        # the resume callbacks must not run until they have completed:
        def slow_fail() -> None:
            self.record("fail-start")
            time.sleep(0.6)
            self.record("fail-end")

        self.watcher.add_fail_callback(slow_fail)
        self.watcher.add_resume_callback(lambda: self.record("resume"))
        self.stall_ui_thread(0.4, 2)
        self.assertEqual([event for event, _ in self.events],
                         ["stall", "fail-start", "fail-end", "resume"])


def main():
    unittest.main()


if __name__ == '__main__':
    main()
