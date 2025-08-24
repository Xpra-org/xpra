# This file is part of Xpra.
# Copyright (C) 2013 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.


from weakref import WeakSet
from threading import Thread, Lock
from queue import Queue
from collections.abc import Callable

from xpra.os_util import gi_import
from xpra.exit_codes import ExitValue
from xpra.log import Logger
from xpra.util.str_fn import repr_ellipsized

log = Logger("util")


class WorkerThread(Thread):
    """
        A background thread which calls the functions we post to it.
        The functions are placed in a queue and only called once,
        when this thread gets around to it.
    """
    __slots__ = ("items", "exit", "daemon_work_items")

    def __init__(self):
        super().__init__(name="WorkerThread", daemon=True)
        self.items: Queue[Callable | None] = Queue()
        self.exit = False
        self.daemon_work_items: WeakSet[Callable] = WeakSet()

    def __repr__(self):
        return f"WorkerThread(items={self.items.qsize()}, exit={self.exit})"

    def stop(self, force: bool = False) -> None:
        if self.exit:
            return
        items = tuple(x for x in self.items.queue if x is not None and x not in self.daemon_work_items)
        log("WorkerThread.stop(%s) %i items still in work queue: %s", force, len(items), items)
        if force:
            if items:
                log.warn("Worker stop: %s items in the queue will not be run!", len(items))
                for x in list(self.items.queue):
                    if x:
                        log.warn(" - %s", x)
                self.items.put(None)
                self.items = Queue()
            self.exit = True
        else:
            if items:
                log.info("waiting for %s items in work queue to complete", len(items))
        self.items.put(None)

    def add(self, item: Callable, allow_duplicates: bool = True, daemon: bool = False) -> None:
        if self.items.qsize() > 10:
            log.warn("WorkerThread.items queue size is %s", self.items.qsize())
            log.warn(" items: %s", repr_ellipsized(tuple(self.items.queue)))
        if not allow_duplicates and item in self.items.queue:
            return
        self.items.put(item)
        if daemon:
            self.daemon_work_items.add(item)

    def run(self) -> ExitValue:
        log("WorkerThread.run() starting")
        while not self.exit:
            item = self.items.get()
            if item is None:
                log("WorkerThread.run() found end of queue marker")
                self.exit = True
                break
            with log.trap_error("Error in worker thread processing item %s", item):
                log("WorkerThread.run() calling %s (queue size=%s)", item, self.items.qsize())
                item()
        log("WorkerThread.run() ended (queue size=%s)", self.items.qsize())
        return 0


# only one worker thread for now:
singleton: WorkerThread | None = None
# locking to ensure multithreaded code doesn't create more than one
lock = Lock()


def get_worker(create: bool = True) -> WorkerThread | None:
    global singleton
    # fast path (no lock):
    if singleton is not None or not create:
        return singleton
    with lock:
        if not singleton:
            singleton = WorkerThread()
            singleton.start()
    return singleton


def add_work_item(item: Callable, allow_duplicates: bool = False, daemon: bool = True) -> None:
    w = get_worker(True)
    log("add_work_item(%s, %s, %s) worker=%s", item, allow_duplicates, daemon, w)
    assert w is not None
    w.add(item, allow_duplicates, daemon)


def stop_worker(force: bool = False) -> None:
    w = get_worker(False)
    log("stop_worker(%s) worker=%s", force, w)
    if w:
        w.stop(force)


def quit_worker(callback: Callable) -> None:
    w = get_worker()
    log("clean_quit: worker=%s", w)
    if not w:
        callback()
        return
    stop_worker()
    try:
        w.join(0.05)
    except Exception:
        pass
    if not w.is_alive():
        callback()
        return

    def quit_timer() -> None:
        log("quit_timer() worker=%s", w)
        if w and w.is_alive():
            # wait up to 1 second for the worker thread to exit
            try:
                w.join(1)
            except Exception:
                pass
            if w.is_alive():
                # still alive, force stop:
                stop_worker(True)
                try:
                    w.wait(1)
                except Exception:
                    pass
        callback()

    glib = gi_import("GLib")
    glib.timeout_add(250, quit_timer)
    log("clean_quit(..) quit timer scheduled, worker=%s", w)
