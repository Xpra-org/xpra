# This file is part of Xpra.
# Copyright (C) 2013 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from queue import SimpleQueue
from threading import Timer, RLock
from typing import Any, TypeAlias
from collections.abc import Callable, Sequence

from xpra.util.objects import AtomicInteger
from xpra.log import Logger

log = Logger("util")

ScheduledItemType: TypeAlias = tuple[Callable, Sequence[Any], dict[str, Any]]


# emulate the glib main loop using a single thread + queue:
class QueueScheduler:
    __slots__ = ("main_queue", "exit", "timer_id", "timers", "timer_lock")

    def __init__(self):
        self.main_queue: SimpleQueue[ScheduledItemType | None] = SimpleQueue()
        self.exit = False
        self.timer_id = AtomicInteger()
        self.timers: dict[int, Timer | None] = {}
        self.timer_lock = RLock()

    def source_remove(self, tid: int) -> None:
        log("source_remove(%i)", tid)
        with self.timer_lock:
            timer = self.timers.pop(tid, None)
            if timer:
                timer.cancel()

    def idle_add(self, fn: Callable, *args, **kwargs) -> int:
        tid = self.timer_id.increase()
        self.main_queue.put((self.idle_repeat_call, (tid, fn, args, kwargs), {}))
        # add an entry,
        # but use the value None to stop us from trying to call cancel()
        self.timers[tid] = None
        return tid

    def idle_repeat_call(self, tid: int, fn: Callable, args, kwargs):
        if tid not in self.timers:
            return False  # cancelled
        return fn(*args, **kwargs)

    def timeout_add(self, timeout: int, fn: Callable, *args, **kwargs) -> int:
        tid = self.timer_id.increase()
        self.do_timeout_add(tid, timeout, fn, *args, **kwargs)
        return tid

    def do_timeout_add(self, tid: int, timeout: int, fn: Callable, *args, **kwargs) -> None:
        # emulate glib's timeout_add using Timers
        args = (tid, timeout, fn, args, kwargs)
        t = Timer(timeout / 1000.0, self.queue_timeout_function, args)
        self.timers[tid] = t
        t.start()

    def queue_timeout_function(self, tid: int, timeout: int, fn: Callable, fn_args, fn_kwargs) -> None:
        if tid not in self.timers:  # pragma: no cover
            return  # cancelled
        # add to run queue:
        mqargs = (tid, timeout, fn, fn_args, fn_kwargs)
        self.main_queue.put((self.timeout_repeat_call, mqargs, {}))

    def timeout_repeat_call(self, tid: int, timeout: int, fn: Callable, fn_args, fn_kwargs) -> bool:
        # executes the function then re-schedules it (if it returns True)
        if tid not in self.timers:  # pragma: no cover
            return False  # cancelled
        v = fn(*fn_args, **fn_kwargs)
        if bool(v):
            # create a new timer with the same tid:
            with self.timer_lock:
                if tid in self.timers:
                    self.do_timeout_add(tid, timeout, fn, *fn_args, **fn_kwargs)
        else:
            self.timers.pop(tid, None)
        # we do the scheduling via timers, so always return False here
        # so that the main queue won't re-schedule this function call itself:
        return False

    def run(self) -> None:
        log("run() queue has %s items already in it", self.main_queue.qsize())
        # process "idle_add"/"timeout_add" events in the main loop:
        while not self.exit:
            log("run() size=%s", self.main_queue.qsize())
            v = self.main_queue.get()
            if v is None:
                log("run() None exit marker")
                break
            fn, args, kwargs = v
            log("run() %s%s%s", fn, args, kwargs)
            with log.trap_error(f"Error during main loop callback {fn}"):
                r = fn(*args, **kwargs)
                if bool(r):
                    # re-run it
                    self.main_queue.put(v)
        self.exit = True

    def stop(self) -> None:
        self.exit = True
        self.stop_main_queue()

    def stop_main_queue(self) -> None:
        self.main_queue.put(None)
        # empty the main queue:
        q: SimpleQueue = SimpleQueue()
        q.put(None)
        self.main_queue = q
