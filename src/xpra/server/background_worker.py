# coding=utf8
# This file is part of Xpra.
# Copyright (C) 2013 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.


from threading import Thread, Lock
from xpra.os_util import Queue

from xpra.log import Logger
log = Logger()
debug = log.debug


class Worker_Thread(Thread):

    def __init__(self):
        Thread.__init__(self, name="Worker_Thread")
        self.items = Queue()
        self.exit = False
        self.setDaemon(True)

    def stop(self, force=False):
        if force:
            if self.items.qsize()>0:
                log.warn("Worker_Thread.stop(%s) %s items in work queue will not run!", force, self.items.qsize())
            self.exit = True
        else:
            if self.items.qsize()>0:
                log.info("waiting for %s items in work queue to complete", self.items.qsize())
        debug("Worker_Thread.stop(%s) %s items in work queue: ", force, self.items)
        self.items.put(None)

    def add(self, item):
        if self.items.qsize()>10:
            log.warn("Worker_Thread.items queue size is %s", self.items.qsize())
        self.items.put(item)

    def run(self):
        debug("Worker_Thread.run() starting")
        while not self.exit:
            item = self.items.get()
            if item is None:
                break
            try:
                debug("Worker_Thread.run() calling %s (queue size=%s)", item, self.items.qsize())
                item()
            except:
                log.error("Worker_Thread.run() error on %s", item, exc_info=True)
        debug("Worker_Thread.run() ended")

#only one worker thread for now:
singleton = None
#locking to ensure multi-threaded code doesn't create more than one
lock = Lock()

def get_worker(create=True):
    global singleton
    #fast path:
    if singleton is not None or not create:
        return singleton
    lock.acquire()
    if singleton:
        return singleton
    singleton = Worker_Thread()
    singleton.start()
    lock.release()
    return singleton

def add_work_item(item):
    get_worker().add(item)

def stop_worker(force=False):
    w = get_worker(False)
    if w:
        w.stop(force)
