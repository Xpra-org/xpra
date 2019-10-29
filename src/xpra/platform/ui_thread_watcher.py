# This file is part of Xpra.
# Copyright (C) 2013-2016 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import threading
from threading import Event

from xpra.make_thread import start_thread
from xpra.os_util import monotonic_time
from xpra.util import envint
from xpra.log import Logger

log = Logger("util")

FAKE_UI_LOCKUPS = envint("XPRA_FAKE_UI_LOCKUPS")
POLLING = envint("XPRA_UI_THREAD_POLLING", 500)


class UI_thread_watcher:
    """
        Allows us to register callbacks
        to fire when the UI thread fails to run
        or when it resumes.
        We run a dedicated thread to verify that
        the UI thread has run since the last time it was
        scheduled to run.
        Beware that the callbacks (fail, resume and alive)
        will run from different threads..
    """
    def __init__(self, timeout_add, source_remove, polling_timeout):
        self.timeout_add = timeout_add
        self.source_remove = source_remove
        self.polling_timeout = polling_timeout
        self.max_delta = polling_timeout * 2
        self.init_vars()

    def init_vars(self):
        self.alive_callbacks = []
        self.fail_callbacks = []
        self.resume_callbacks = []
        self.UI_blocked = False
        self.last_UI_thread_time = 0
        self.ui_wakeup_timer = None
        self.exit = Event()

    def start(self):
        if self.last_UI_thread_time>0:
            log.warn("UI thread watcher already started!")
            return
        #run once to initialize:
        self.UI_thread_wakeup()
        if self.polling_timeout>0:
            start_thread(self.poll_UI_loop, "UI thread polling", daemon=True)
        else:
            log("not starting an IO polling thread")
        if FAKE_UI_LOCKUPS>0:
            #watch out: sleeping in UI thread!
            def sleep_in_ui_thread(*args):
                t = threading.current_thread()
                log.warn("sleep_in_ui_thread%s pausing %s for %ims", args, t, FAKE_UI_LOCKUPS)
                import time
                time.sleep(FAKE_UI_LOCKUPS/1000.0)
                return True
            self.timeout_add(10*1000+FAKE_UI_LOCKUPS, sleep_in_ui_thread)

    def stop(self):
        self.exit.set()

    def add_fail_callback(self, cb):
        self.fail_callbacks.append(cb)

    def add_resume_callback(self, cb):
        self.resume_callbacks.append(cb)

    def add_alive_callback(self, cb):
        self.alive_callbacks.append(cb)


    def remove_fail_callback(self, cb):
        self.fail_callbacks.remove(cb)

    def remove_resume_callback(self, cb):
        self.resume_callbacks.remove(cb)

    def remove_alive_callback(self, cb):
        self.alive_callbacks.remove(cb)


    def run_callbacks(self, callbacks):
        for x in callbacks:
            try:
                x()
            except Exception:
                log.error("failed to run %s", x, exc_info=True)

    def UI_thread_wakeup(self, scheduled_at=0):
        if scheduled_at:
            elapsed = monotonic_time()-scheduled_at
        else:
            elapsed = 0
        self.ui_wakeup_timer = None
        log("UI_thread_wakeup() elapsed=%.2fms", 1000*elapsed)
        self.last_UI_thread_time = monotonic_time()
        #UI thread was blocked?
        if self.UI_blocked:
            log.info("UI thread is running again, resuming")
            self.UI_blocked = False
            self.run_callbacks(self.resume_callbacks)
        return False

    def poll_UI_loop(self):
        log("poll_UI_loop() running")
        while not self.exit.isSet():
            delta = monotonic_time()-self.last_UI_thread_time
            log("poll_UI_loop() last_UI_thread_time was %.1f seconds ago (max %i), UI_blocked=%s",
                delta, self.max_delta/1000, self.UI_blocked)
            if delta>self.max_delta/1000.0:
                #UI thread is (still?) blocked:
                if not self.UI_blocked:
                    log.info("UI thread is now blocked")
                    self.UI_blocked = True
                    self.run_callbacks(self.fail_callbacks)
            else:
                #seems to be ok:
                log("poll_UI_loop() ok, firing %s", self.alive_callbacks)
                self.run_callbacks(self.alive_callbacks)
            now = monotonic_time()
            self.ui_wakeup_timer = self.timeout_add(0, self.UI_thread_wakeup, now)
            wstart = monotonic_time()
            wait_time = self.polling_timeout/1000.0     #convert to seconds
            self.exit.wait(wait_time)
            if not self.exit.isSet():
                wdelta = monotonic_time() - wstart
                log("wait(%.4f) actually waited %.4f", self.polling_timeout/1000.0, wdelta)
                if wdelta>(wait_time+1):
                    #this can be caused by an ntp update?
                    #or just by suspend + resume
                    log.warn("Warning: long timer waiting time,")
                    log.warn(" UI thread polling waited %.1f seconds longer than intended (%.1f vs %.1f)",
                             wdelta-wait_time, wdelta, wait_time)
                    #force run resume (even if we never fired the fail callbacks)
                    self.UI_blocked = False
                    self.UI_thread_wakeup()
        self.init_vars()
        log("poll_UI_loop() ended")
        uiwt = self.ui_wakeup_timer
        if uiwt:
            self.ui_wakeup_timer = None
            self.source_remove(uiwt)


UI_watcher = None
def get_UI_watcher(timeout_add=None, source_remove=None):
    global UI_watcher
    if UI_watcher is None and timeout_add:
        UI_watcher = UI_thread_watcher(timeout_add, source_remove, POLLING)
        log("get_UI_watcher(%s)", timeout_add)
    return UI_watcher
