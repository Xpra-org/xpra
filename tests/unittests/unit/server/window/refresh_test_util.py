# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.


class FakeClock:
    def __init__(self, now=100.0):
        self.now = now

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


class FakeScheduler:
    def __init__(self):
        self.tasks = {}
        self.scheduled = []
        self.cancelled = []
        self.next_id = 1

    def timeout_add(self, delay, callback, *args):
        tid = self.next_id
        self.next_id += 1
        self.tasks[tid] = callback, args
        self.scheduled.append((tid, delay))
        return tid

    def source_remove(self, tid):
        self.cancelled.append(tid)
        self.tasks.pop(tid, None)

    def idle_add(self, callback, *args):
        return self.timeout_add(0, callback, *args)

    def fire(self, tid):
        callback, args = self.tasks.pop(tid)
        return callback(*args)
