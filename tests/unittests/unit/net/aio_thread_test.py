#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Netflix, Inc.
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

# ABOUTME: Tests for ThreadedAsyncioLoop.stop() — verifies the loop is stopped
# ABOUTME: and the daemon thread is joined, which is what prevents the uvloop
# ABOUTME: callback vs Py_FinalizeEx race that crashes in PyGILState_Ensure
# ABOUTME: -> new_threadstate(NULL).

import unittest

from xpra.net.aio.thread import ThreadedAsyncioLoop


class TestThreadedAsyncioLoopStop(unittest.TestCase):

    def test_stop_terminates_loop_and_joins_thread(self):
        tl = ThreadedAsyncioLoop()
        thread = tl._thread
        self.assertIsNotNone(thread)
        self.assertTrue(thread.is_alive())
        loop = tl.loop
        self.assertIsNotNone(loop)
        # We don't assert loop.is_running() here: wait_for_loop() only
        # waits for self.loop to be assigned, not for run_forever() to
        # start. Under scheduler pressure that assertion would flake.

        tl.stop()

        self.assertFalse(thread.is_alive(), "asyncio thread did not exit")
        # run_forever() returns, then loop.close() runs at the end of
        # the thread; by the time stop() returns from thread.join() the
        # loop should be closed.
        self.assertTrue(loop.is_closed(), "loop was not closed on shutdown")

    def test_stop_is_idempotent(self):
        tl = ThreadedAsyncioLoop()
        tl.stop()
        tl.stop()


if __name__ == "__main__":
    unittest.main()
