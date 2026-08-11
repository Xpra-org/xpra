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
from xpra.util.env import envint, envbool
from xpra.log import Logger

GLib = gi_import("GLib")

log = Logger("util", "event")

FAKE_UI_LOCKUPS = envint("XPRA_FAKE_UI_LOCKUPS")
POLLING = envint("XPRA_UI_THREAD_POLLING", 500)
MAX_DELTA = envint("XPRA_UI_THREAD_MAX_DELTA", 2000 + POLLING * 2)
ANNOUNCE_TIMEOUT = envint("XPRA_ANNOUNCE_BLOCKED", POLLING)
DUMP_FRAMES = envbool("XPRA_UI_THREAD_DUMP_FRAMES", True)


def run_callbacks(callbacks: list[Callable[[], None]]) -> None:
    for callback in tuple(callbacks):
        with log.trap_error("Error running UI watcher callback %s", callback):
            callback()


def log_message(message:str):
    log.info(message)


class UIThreadWatcher:
    """
        Allows us to register callbacks
        to fire when the UI thread fails to run
        or when it resumes.
        We run a dedicated thread to verify that
        the UI thread has run since the last time it was
        scheduled to run.
        Beware that the `alive` and `fail` callbacks run from the polling thread,
        only the `resume` callbacks are run from the UI thread.
    """

    def __init__(self, polling_timeout: int, max_delta: int, announce_timeout: float):
        self.polling_timeout = polling_timeout
        self.max_delta = max_delta
        self.announce_timeout: float = announce_timeout / 1000.0 if announce_timeout else float('inf')
        # the callbacks and `show_message` belong to whoever registers them:
        # this class never clears them, so that stopping the watcher
        # (which is a process-wide singleton) cannot silently discard
        # the callbacks registered by another subsystem - see `remove_*_callback`
        self.alive_callbacks: list[Callable[[], None]] = []
        self.fail_callbacks: list[Callable[[], None]] = []
        self.resume_callbacks: list[Callable[[], None]] = []
        self.show_message: Callable[[str], None] = log_message
        if DUMP_FRAMES:
            # registered first, so the stacks are captured before any other
            # fail callback gets a chance to run (and to move the UI thread on):
            self.add_fail_callback(self.dump_ui_thread_frames)
        # this event is created once and re-used: `start` clears it and `stop` sets it,
        # so that the watcher can be started again (ie: when the client re-connects)
        self.exit: Event = Event()
        self.started: bool = False
        # bumped by every `start`, so that the polling thread of a previous run
        # can tell that it has been superseded and must not touch the new run's state:
        self.generation: int = 0
        self.reset_state()

    def reset_state(self) -> None:
        # the polling state - reset by `start`, from the thread owning the watcher:
        self.ui_blocked: bool = False
        self.announced_blocked: bool = False
        self.last_ui_thread_time: float = 0
        self.ui_wakeup_timer: int = 0

    def start(self) -> None:
        if self.started:
            log.warn("UI thread watcher already started!")
            return
        self.started = True
        self.reset_state()
        self.exit.clear()
        self.generation += 1
        if self.polling_timeout > 0:
            start_thread(self.poll_ui_loop, "UI thread polling", daemon=True, args=(self.generation,))
        else:
            log("not starting an IO polling thread")
        if FAKE_UI_LOCKUPS > 0:
            # watch out: sleeping in UI thread!
            def sleep_in_ui_thread() -> bool:
                t = threading.current_thread()
                name = getattr(t, "name", str(t))
                log.warn("Warning: pausing %r for %ims", name, FAKE_UI_LOCKUPS)
                time.sleep(FAKE_UI_LOCKUPS / 1000.0)
                return True

            GLib.timeout_add(10 * 1000 + FAKE_UI_LOCKUPS, sleep_in_ui_thread)

    def stop(self) -> None:
        self.started = False
        self.cancel_ui_wakeup_timer()
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

    def dump_ui_thread_frames(self) -> None:
        """
        Runs from the polling thread as soon as the UI thread is declared blocked,
        so that `sys._current_frames()` shows us what it is stuck in.
        Beware: this can only ever fire if the polling thread is still running,
        so it will not catch a stall of the whole process
        (ie: the GIL being held by a native callback) - use an external
        sampling profiler for those.
        """
        from xpra.util.pysystem import dump_all_frames
        log("UI thread blocked for more than %ims, dumping all frames:", self.max_delta)
        dump_all_frames(log)

    def tick(self) -> None:
        self.last_ui_thread_time = monotonic()

    def ui_thread_wakeup(self, scheduled_at: float = 0) -> bool:
        if scheduled_at:
            elapsed = monotonic() - scheduled_at
        else:
            elapsed = 0
        log("ui_thread_wakeup(%s) elapsed=%.2fms", scheduled_at, 1000 * elapsed)
        self.last_ui_thread_time = monotonic()
        # UI thread was blocked?
        if self.ui_blocked:
            if self.announced_blocked:
                self.show_message("UI thread is running again, resuming")
                self.announced_blocked = False
            self.ui_blocked = False
            run_callbacks(self.resume_callbacks)
        self.ui_wakeup_timer = 0
        return False

    def poll_ui_loop(self, generation: int) -> None:
        log("poll_ui_loop(%i) running", generation)
        while self.generation == generation and not self.exit.is_set():
            if self.last_ui_thread_time > 0:
                delta = monotonic() - self.last_ui_thread_time
                if self.ui_blocked:
                    log("poll_ui_loop() last_ui_thread_time was %ims ago (max %i), ui_blocked=%s",
                        delta * 1000, self.max_delta, self.ui_blocked)
                if delta > self.max_delta / 1000.0:
                    # UI thread is (still?) blocked:
                    if not self.ui_blocked:
                        self.ui_blocked = True
                        run_callbacks(self.fail_callbacks)
                    if not self.announced_blocked and delta > self.announce_timeout:
                        self.announced_blocked = True
                        self.show_message("UI thread is now blocked")
                else:
                    # seems to be ok:
                    log("poll_ui_loop() ok, firing %s", self.alive_callbacks)
                    run_callbacks(self.alive_callbacks)
            now = monotonic()
            self.ui_wakeup_timer = GLib.timeout_add(0, self.ui_thread_wakeup, now)
            wstart = monotonic()
            wait_time = self.polling_timeout / 1000.0  # convert to seconds
            self.exit.wait(wait_time)
            if not self.exit.is_set():
                wdelta = monotonic() - wstart
                log("wait(%.4f) actually waited %ims", self.polling_timeout / 1000.0, wdelta * 1000)
                if wdelta > (wait_time + 1):
                    # this can be caused by suspend + resume
                    if wdelta > 60 and not self.ui_blocked:
                        log.info("no service for %i seconds", wdelta)
                    else:
                        log.warn("Warning: long timer waiting time,")
                        log.warn(" UI thread polling waited %.1f seconds longer than intended (%.1f vs %.1f)",
                                 wdelta - wait_time, wdelta, wait_time)
                    # the UI thread was very likely frozen with us,
                    # so force run resume (even if we never fired the fail callbacks),
                    # from the UI thread - where the callbacks belong:
                    self.ui_blocked = True
                    self.tick()
                    GLib.idle_add(self.ui_thread_wakeup)
        log("poll_ui_loop(%i) ended", generation)
        if self.generation == generation:
            # don't touch the state of a newer run:
            self.cancel_ui_wakeup_timer()

    def cancel_ui_wakeup_timer(self) -> None:
        if uiwt := self.ui_wakeup_timer:
            self.ui_wakeup_timer = 0
            GLib.source_remove(uiwt)


ui_watcher: UIThreadWatcher | None = None


def get_ui_watcher() -> UIThreadWatcher | None:
    global ui_watcher
    if ui_watcher is None:
        ui_watcher = UIThreadWatcher(POLLING, MAX_DELTA, ANNOUNCE_TIMEOUT)
        log("get_ui_watcher()=%s", ui_watcher)
    return ui_watcher
