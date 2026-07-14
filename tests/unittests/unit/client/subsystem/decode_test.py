#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest
from threading import Event

from xpra.client.base.stub import StubClientSubsystem
from xpra.client.subsystem.decode import Decode


class FakeClient:
    """ minimal stand-in for the owning client (see `StubClientSubsystem.get_subsystem`) """

    def __init__(self):
        self.exit_code = None
        self.subsystems: dict[str, object] = {}

    @staticmethod
    def idle_add(fn, *args) -> int:
        fn(*args)
        return 0

    timeout_add = idle_add

    @staticmethod
    def source_remove(_tid: int) -> None:
        """ nothing to remove: `idle_add` above runs synchronously """

    def add_subsystem(self, subsystem) -> None:
        subsystem.client = self
        self.subsystems[subsystem.PREFIX] = subsystem


class DecodeTest(unittest.TestCase):

    @staticmethod
    def make_decode(client=None) -> Decode:
        decode = Decode(client=client or FakeClient())
        # the seccomp filter and the codec preload are not what we are testing here,
        # and installing a filter would apply to the whole test run:
        decode.preload = lambda: None
        decode.install_seccomp = lambda: None
        return decode

    def test_add_work_runs_on_the_decode_thread(self):
        decode = self.make_decode()
        done = Event()
        calls = []
        decode.run()
        try:
            decode.add_work(calls.append, ("first", 1))
            decode.add_work(calls.append, ("second", 2))
            decode.add_work(lambda: done.set())
            self.assertTrue(done.wait(5), "the decode thread did not run the work items")
        finally:
            decode.cleanup()
        # the queue is FIFO: draw packets must be painted in the order they arrived
        self.assertEqual(calls, [("first", 1), ("second", 2)])

    def test_error_does_not_kill_the_loop(self):
        decode = self.make_decode()
        done = Event()

        def fail() -> None:
            raise ValueError("simulated decoding error")

        decode.run()
        try:
            decode.add_work(fail)
            decode.add_work(done.set)
            self.assertTrue(done.wait(5), "a failed work item stopped the decode thread")
        finally:
            decode.cleanup()

    def test_cleanup_stops_the_thread(self):
        decode = self.make_decode()
        thread = decode.run() or decode._thread
        decode.cleanup()
        thread.join(5)
        self.assertFalse(thread.is_alive(), "the exit marker did not stop the decode thread")

    def test_add_decode_work_uses_the_decode_subsystem(self):
        client = FakeClient()
        decode = self.make_decode(client)
        client.add_subsystem(decode)
        consumer = StubClientSubsystem(client=client)
        done = Event()
        decode.run()
        try:
            consumer.add_decode_work(done.set)
            self.assertTrue(done.wait(5), "the work item was not queued on the decode thread")
        finally:
            decode.cleanup()

    def test_add_decode_work_runs_inline_without_a_decode_subsystem(self):
        # subsystems are unit-tested in isolation, with no `decode` subsystem to defer to:
        consumer = StubClientSubsystem(client=FakeClient())
        calls = []
        consumer.add_decode_work(calls.append, "inline")
        self.assertEqual(calls, ["inline"])


def main():
    unittest.main()


if __name__ == "__main__":
    main()
