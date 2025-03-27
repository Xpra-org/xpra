# This file is part of Xpra.
# Copyright (C) 2013 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import time
import threading
from time import monotonic
from threading import Event
from collections.abc import Callable

from xpra.os_util import gi_import
from xpra.util.thread import start_thread
from xpra.util.env import envint
from xpra.log import Logger

GLib = gi_import("GLib")

log = Logger("util")

FAKE_UI_LOCKUPS = envint("XPRA_FAKE_UI_LOCKUPS")
POLLING = envint("XPRA_UI_THREAD_POLLING", 500)
ANNOUNCE_TIMEOUT = envint("XPRA_ANNOUNCE_BLOCKED", POLLING)


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

    def __init__(self, polling_timeout: int, announce_timeout: float):
        self.polling_timeout = polling_timeout
        self.max_delta: int = polling_timeout * 2
        self.announce_timeout: float = announce_timeout / 1000.0 if announce_timeout else float('inf')
        self.init_vars()

    def init_vars(self) -> None:
        self.alive_callbacks: list[Callable[[], None]] = []
        self.fail_callbacks: list[Callable[[], None]] = []
        self.resume_callbacks: list[Callable[[], None]] = []
        self.UI_blocked: bool = False
        self.announced_blocked: bool = False
        self.last_UI_thread_time: float = 0
        self.ui_wakeup_timer: int = 0
        self.exit: Event = Event()

    def start(self) -> None:
        if self.last_UI_thread_time > 0:
            log.warn("UI thread watcher already started!")
            return
        if self.polling_timeout > 0:
            start_thread(self.poll_UI_loop, "UI thread polling", daemon=True)
        else:
            log("not starting an IO polling thread")
        if FAKE_UI_LOCKUPS > 0:
            # watch out: sleeping in UI thread!
            def sleep_in_ui_thread(*args):
                t = threading.current_thread()
                log.warn("sleep_in_ui_thread%s pausing %s for %ims", args, t, FAKE_UI_LOCKUPS)
                time.sleep(FAKE_UI_LOCKUPS / 1000.0)
                return True

            GLib.timeout_add(10 * 1000 + FAKE_UI_LOCKUPS, sleep_in_ui_thread)

    def stop(self) -> None:
        self.exit.set()

    def add_fail_callback(self, cb: Callable[[], None]) -> None:
        self.fail_callbacks.append(cb)

    def add_resume_callback(self, cb: Callable[[], None]) -> None:
        self.resume_callbacks.append(cb)

    def add_alive_callback(self, cb: Callable[[], None]) -> None:
        self.alive_callbacks.append(cb)

    def remove_fail_callback(self, cb: Callable[[], None]) -> None:
        self.fail_callbacks.remove(cb)

    def remove_resume_callback(self, cb: Callable[[], None]) -> None:
        self.resume_callbacks.remove(cb)

    def remove_alive_callback(self, cb: Callable[[], None]) -> None:
        self.alive_callbacks.remove(cb)

    @staticmethod
    def run_callbacks(callbacks: list[Callable[[], None]]) -> None:
        for callback in callbacks:
            with log.trap_error("Error running UI watcher callback %s", callback):
                callback()

    def UI_thread_wakeup(self, scheduled_at: float = 0) -> bool:
        if scheduled_at:
            elapsed = monotonic() - scheduled_at
        else:
            elapsed = 0
        self.ui_wakeup_timer = 0
        log("UI_thread_wakeup(%s) elapsed=%.2fms", scheduled_at, 1000 * elapsed)
        self.last_UI_thread_time = monotonic()
        # UI thread was blocked?
        if self.UI_blocked:
            if self.announced_blocked:
                log.info("UI thread is running again, resuming")
                self.announced_blocked = False
            self.UI_blocked = False
            self.run_callbacks(self.resume_callbacks)
        return False

    def poll_UI_loop(self) -> None:
        log("poll_UI_loop() running")
        while not self.exit.is_set():
            if self.last_UI_thread_time > 0:
                delta = monotonic() - self.last_UI_thread_time
                if self.UI_blocked:
                    log("poll_UI_loop() last_UI_thread_time was %ims ago (max %i), UI_blocked=%s",
                        delta * 1000, self.max_delta, self.UI_blocked)
                if delta > self.max_delta / 1000.0:
                    # UI thread is (still?) blocked:
                    if not self.UI_blocked:
                        self.UI_blocked = True
                        self.run_callbacks(self.fail_callbacks)
                    if not self.announced_blocked and delta > self.announce_timeout:
                        self.announced_blocked = True
                        log.info("UI thread is now blocked")
                else:
                    # seems to be ok:
                    log("poll_UI_loop() ok, firing %s", self.alive_callbacks)
                    self.run_callbacks(self.alive_callbacks)
            now = monotonic()
            self.ui_wakeup_timer = GLib.timeout_add(0, self.UI_thread_wakeup, now)
            wstart = monotonic()
            wait_time = self.polling_timeout / 1000.0  # convert to seconds
            self.exit.wait(wait_time)
            if not self.exit.is_set():
                wdelta = monotonic() - wstart
                log("wait(%.4f) actually waited %ims", self.polling_timeout / 1000.0, wdelta * 1000)
                if wdelta > (wait_time + 1):
                    # this can be caused by suspend + resume
                    if wdelta > 60 and not self.UI_blocked:
                        log.info("no service for %i seconds", wdelta)
                    else:
                        log.warn("Warning: long timer waiting time,")
                        log.warn(" UI thread polling waited %.1f seconds longer than intended (%.1f vs %.1f)",
                                 wdelta - wait_time, wdelta, wait_time)
                    # force run resume (even if we never fired the fail callbacks)
                    self.UI_blocked = False
                    self.UI_thread_wakeup()
        self.init_vars()
        log("poll_UI_loop() ended")
        uiwt = self.ui_wakeup_timer
        if uiwt:
            self.ui_wakeup_timer = 0
            GLib.source_remove(uiwt)


UI_watcher: UI_thread_watcher | None = None


def get_UI_watcher() -> UI_thread_watcher | None:
    global UI_watcher
    if UI_watcher is None:
        UI_watcher = UI_thread_watcher(POLLING, ANNOUNCE_TIMEOUT)
        log("get_UI_watcher()=%s", UI_watcher)
    return UI_watcher
