# This file is part of Xpra.
# Copyright (C) 2013 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import time
from threading import Event
from xpra.daemon_thread import make_daemon_thread
from xpra.log import Logger, debug_if_env
log = Logger()
debug = debug_if_env(log, "XPRA_UIWATCHER_DEBUG")

from xpra.platform.features import UI_THREAD_POLLING
FAKE_UI_LOCKUPS = int(os.environ.get("XPRA_FAKE_UI_LOCKUPS", "0"))
if FAKE_UI_LOCKUPS>0 and UI_THREAD_POLLING<=0:
    #even if the platform normally disables UI thread polling,
    #we need it for testing:
    UI_THREAD_POLLING = 1000
POLLING = int(os.environ.get("XPRA_UI_THREAD_POLLING", UI_THREAD_POLLING))


class UI_thread_watcher(object):
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
    def __init__(self, timeout_add, polling_timeout):
        self.timeout_add = timeout_add
        self.polling_timeout = polling_timeout
        self.max_delta = polling_timeout * 2
        self.alive_callbacks = []
        self.fail_callbacks = []
        self.resume_callbacks = []
        self.UI_blocked = False
        self.last_UI_thread_time = 0
        self.exit = Event()

    def start(self):
        if self.last_UI_thread_time>0:
            log.warn("UI thread watcher already started!")
            return
        #run once to initialize:
        self.UI_thread_wakeup()
        if self.polling_timeout>0:
            make_daemon_thread(self.poll_UI_loop, "UI thread polling").start()
        else:
            debug("not starting an IO polling thread")
        if FAKE_UI_LOCKUPS>0:
            #watch out: sleeping in UI thread!
            def sleep_in_ui_thread(*args):
                time.sleep(FAKE_UI_LOCKUPS)
                return True
            self.timeout_add((10+FAKE_UI_LOCKUPS)*1000, sleep_in_ui_thread)

    def stop(self):
        self.exit.set()

    def add_fail_callback(self, cb):
        self.fail_callbacks.append(cb)

    def add_resume_callback(self, cb):
        self.resume_callbacks.append(cb)

    def add_alive_callback(self, cb):
        self.alive_callbacks.append(cb)

    def run_callbacks(self, callbacks):
        for x in callbacks:
            try:
                x()
            except:
                log.error("failed to run %s", x, exc_info=True)

    def UI_thread_wakeup(self):
        debug("UI_thread_wakeup()")
        self.last_UI_thread_time = time.time()
        #UI thread was blocked?
        if self.UI_blocked:
            log.info("UI thread is running again, resuming")
            self.UI_blocked = False
            self.run_callbacks(self.resume_callbacks)
        return False

    def poll_UI_loop(self):
        debug("poll_UI_loop() running")
        while not self.exit.isSet():
            delta = time.time()-self.last_UI_thread_time
            debug("poll_UI_loop() last_UI_thread_time was %.1f seconds ago, UI_blocked=%s", delta, self.UI_blocked)
            if delta>self.max_delta:
                #UI thread is (still?) blocked:
                if not self.UI_blocked:
                    log.info("UI thread is now blocked")
                    self.UI_blocked = True
                    self.run_callbacks(self.fail_callbacks)
            else:
                #seems to be ok:
                debug("poll_UI_loop() ok, firing %s", self.alive_callbacks)
                self.run_callbacks(self.alive_callbacks)
            self.timeout_add(0, self.UI_thread_wakeup)
            self.exit.wait(self.polling_timeout/1000.0)


UI_watcher = None
def get_UI_watcher(timeout_add=None):
    global UI_watcher
    if UI_watcher is None and timeout_add:
        UI_watcher = UI_thread_watcher(timeout_add, POLLING)
    return UI_watcher
