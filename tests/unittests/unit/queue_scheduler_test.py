#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2019-2020 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest

from unit.test_util import silence_error
from xpra.queue_scheduler import QueueScheduler, log


class QueueSchedulerTest(unittest.TestCase):

    def test_idle_timeout(self):
        qs = QueueScheduler()
        calls = []
        def idle_add(arg):
            calls.append(arg)
        qs.idle_add(idle_add, True)
        def timeout_add(arg):
            calls.append(arg)
        qs.timeout_add(100, timeout_add, True)
        qs.timeout_add(500, qs.stop)
        qs.run()
        assert len(calls)==2

    def test_idle_repeat(self):
        qs = QueueScheduler()
        calls = []
        def idle_add(arg):
            calls.append(arg)
            return len(calls)<10
        qs.idle_add(idle_add, True)
        qs.timeout_add(500, qs.stop)
        qs.run()
        assert len(calls)==10

    def test_idle_cancel(self):
        qs = QueueScheduler()
        calls = []
        def idle_add():
            calls.append(True)
            return True
        tid = qs.idle_add(idle_add)
        copy = []
        def cancel():
            qs.source_remove(tid)
            copy[:] = list(calls)
            return False
        qs.timeout_add(500, cancel)
        qs.timeout_add(1000, qs.stop)
        qs.run()
        assert len(calls)==len(copy), "idle_add continued to run!"

    def test_timeout_cancel(self):
        qs = QueueScheduler()
        calls = []
        def timeout_add():
            calls.append(True)
            return True
        tid = qs.timeout_add(10, timeout_add)
        copy = []
        def cancel():
            qs.source_remove(tid)
            copy[:] = list(calls)
            return False
        qs.timeout_add(500, cancel)
        qs.timeout_add(1000, qs.stop)
        qs.run()
        assert len(calls)==len(copy), "idle_add continued to run!"

    def test_source_remove(self):
        qs = QueueScheduler()
        calls = []
        def timeout_add(arg):
            calls.append(arg)
            return True
        t = qs.timeout_add(100, timeout_add, True)
        qs.source_remove(t)
        qs.timeout_add(500, qs.stop)
        qs.run()
        assert not calls

    def test_invalid_remove(self):
        qs = QueueScheduler()
        qs.source_remove(-1)

    def test_idle_raises_exception(self):
        qs = QueueScheduler()
        def raise_exception():
            raise Exception("test scheduler error handling")
        with silence_error(log):
            qs.idle_add(raise_exception)
            qs.timeout_add(500, qs.stop)
            qs.run()

    def test_stop_queue(self):
        qs = QueueScheduler()
        qs.idle_add(qs.stop_main_queue)
        qs.run()

    def test_timer_repeat(self):
        times = list(range(10))
        qs = QueueScheduler()
        def timer_fn():
            times.pop()
            if not times:
                qs.stop()
                return False
            return True
        qs.timeout_add(1, timer_fn)
        qs.timeout_add(2000, qs.stop)
        qs.run()
        assert not times, "items remain in list: %s" % (times,)

def main():
    unittest.main()

if __name__ == '__main__':
    main()
