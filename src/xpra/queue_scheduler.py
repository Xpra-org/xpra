# This file is part of Xpra.
# Copyright (C) 2013-2020 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from queue import Queue
from threading import Timer, RLock

from xpra.util import AtomicInteger
from xpra.log import Logger

log = Logger("util")


#emulate the glib main loop using a single thread + queue:

class QueueScheduler:

    def __init__(self):
        self.main_queue = Queue()
        self.exit = False
        self.timer_id = AtomicInteger()
        self.timers = {}
        self.timer_lock = RLock()

    def source_remove(self, tid : int):
        log("source_remove(%i)", tid)
        with self.timer_lock:
            try:
                timer = self.timers[tid]
                if timer is not None:
                    del self.timers[tid]
                if timer:
                    timer.cancel()
            except KeyError:
                pass

    def idle_add(self, fn : callable, *args, **kwargs) -> int:
        tid = self.timer_id.increase()
        self.main_queue.put((self.idle_repeat_call, (tid, fn, args, kwargs), {}))
        #add an entry,
        #but use the value False to stop us from trying to call cancel()
        self.timers[tid] = False
        return tid

    def idle_repeat_call(self, tid : int, fn : callable, args, kwargs):
        if tid not in self.timers:
            return False    #cancelled
        return fn(*args, **kwargs)

    def timeout_add(self, timeout : int, fn : callable, *args, **kwargs):
        tid = self.timer_id.increase()
        self.do_timeout_add(tid, timeout, fn, *args, **kwargs)
        return tid

    def do_timeout_add(self, tid : int, timeout : int, fn : callable, *args, **kwargs):
        #emulate glib's timeout_add using Timers
        args = (tid, timeout, fn, args, kwargs)
        t = Timer(timeout/1000.0, self.queue_timeout_function, args)
        self.timers[tid] = t
        t.start()

    def queue_timeout_function(self, tid : int, timeout : int, fn : callable, fn_args, fn_kwargs):
        if tid not in self.timers:
            return      #cancelled
        #add to run queue:
        mqargs = [tid, timeout, fn, fn_args, fn_kwargs]
        self.main_queue.put((self.timeout_repeat_call, mqargs, {}))

    def timeout_repeat_call(self, tid : int, timeout : int, fn : callable, fn_args, fn_kwargs):
        #executes the function then re-schedules it (if it returns True)
        if tid not in self.timers:
            return False    #cancelled
        v = fn(*fn_args, **fn_kwargs)
        if bool(v):
            #create a new timer with the same tid:
            with self.timer_lock:
                if tid in self.timers:
                    self.do_timeout_add(tid, timeout, fn, *fn_args, **fn_kwargs)
        else:
            try:
                del self.timers[tid]
            except KeyError:
                pass
        #we do the scheduling via timers, so always return False here
        #so that the main queue won't re-schedule this function call itself:
        return False


    def run(self):
        log("run() queue has %s items already in it", self.main_queue.qsize())
        #process "idle_add"/"timeout_add" events in the main loop:
        while not self.exit:
            log("run() size=%s", self.main_queue.qsize())
            v = self.main_queue.get()
            if v is None:
                log("run() None exit marker")
                break
            fn, args, kwargs = v
            log("run() %s%s%s", fn, args, kwargs)
            try:
                r = fn(*args, **kwargs)
                if bool(r):
                    #re-run it
                    self.main_queue.put(v)
            except Exception:
                log.error("error during main loop callback %s", fn, exc_info=True)
        self.exit = True

    def stop(self):
        self.exit = True
        self.stop_main_queue()

    def stop_main_queue(self):
        self.main_queue.put(None)
        #empty the main queue:
        q = Queue()
        q.put(None)
        self.main_queue = q
