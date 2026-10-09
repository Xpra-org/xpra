# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.


# This class is used by the posix server to ensure
# we reap the dead pids so that they don't become zombies,
# also used for implementing --exit-with-children

import os
import signal
import sys
from time import monotonic
from threading import Lock
from typing import Any
from collections.abc import Callable, Sequence

from xpra.util.env import envint, envbool
from xpra.util.objects import AtomicInteger
from xpra.os_util import POSIX, gi_import
from xpra.log import Logger

GLib = gi_import("GLib")
log = Logger("server", "util", "exec")


sequence = AtomicInteger()
# how long we leave a dead child that is not registered with us
# for its owner to collect its exit status:
UNKNOWN_CHILD_DELAY = envint("XPRA_UNKNOWN_CHILD_DELAY", 5)
REAP_RETRY_DELAY = envint("XPRA_REAP_RETRY_DELAY", 1)
# ie: macos with python < 3.13 does not have `waitid`
HAS_WAITID = hasattr(os, "waitid")


def pid_exists(pid: int) -> bool:
    # posix only: `os.kill` terminates the process on win32!
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except OSError:
        pass
    return True


def is_pending(process) -> bool:
    # `poll()` returned None, but another thread may be collecting its exit status:
    # `Popen` holds its `_waitpid_lock` until it has recorded the `returncode`
    if process.returncode is not None:
        return True
    lock = getattr(process, "_waitpid_lock", None)
    # The waiter may publish its status and release the lock between these reads.
    return bool(lock and lock.locked()) or process.returncode is not None


def get_comm(pid: int) -> str:
    try:
        with open(f"/proc/{pid}/comm", encoding="utf8") as f:
            return f.read().strip()
    except OSError:
        return ""


class PidPopen:
    def __init__(self, pid: int):
        self.pid = pid
        self.returncode: int | None = None
        # same name as in `Popen`, so `is_pending()` can see that it is being reaped:
        self._waitpid_lock = Lock()

    def poll(self) -> int | None:
        if self.returncode is not None or not POSIX:
            return self.returncode
        if not self._waitpid_lock.acquire(False):
            # something else is busy reaping it
            return None
        try:
            if self.returncode is None:
                self._poll()
        finally:
            self._waitpid_lock.release()
        return self.returncode

    def _poll(self) -> None:
        try:
            pid, status = os.waitpid(self.pid, os.WNOHANG)
        except ChildProcessError:
            # not one of our children, so we can only check if it still exists:
            if not pid_exists(self.pid):
                self.returncode = 0
        else:
            if pid:
                self.returncode = os.waitstatus_to_exitcode(status)


class ProcInfo:
    __slots__ = (
        "pid", "pidfile", "pidinode",
        "name", "command", "ignore",
        "forget", "dead", "returncode",
        "callback", "process",
        "sequence", "lock",
    )
    sequence: int
    pid: int
    pidfile: str
    pidinode: int
    name: str
    command: Any
    ignore: bool
    forget: bool
    dead: bool
    returncode: int | None
    callback: Callable | None
    process: Any
    lock: Lock

    def __repr__(self):
        return f"ProcInfo({self.pid} : {self.command})"

    def get_info(self) -> dict[str, Any]:
        info = {
            "pid": self.pid,
            "name": self.name,
            "command": self.command,
            "ignore": self.ignore,
            "forget": self.forget,
            # not base types:
            # callback, process
            "dead": self.dead,
            "pidfile": self.pidfile,
            "pidinode": self.pidinode,
        }
        if self.returncode is not None:
            info["returncode"] = self.returncode
        return info


# Processes may be registered from any thread, and their exit can be detected
# from more than one thread at the same time, so the death of each process
# is handled under its own `ProcInfo.lock`.
# We avoid `waitpid(-1)`: that would steal the exit status from `Popen` objects,
# and their own `wait()` would then return 0 - which the exec authentication module
# would treat as success.
# Registered processes are reaped through their own `poll()` method,
# and other dead children are only reaped after giving their owner some time.
class ChildReaper:
    __slots__ = ("_quit", "_proc_info", "_proc_lock", "_pending", "_retry")

    # note: the quit callback will fire only once!

    def __init__(self, quit_cb=None):
        log("ChildReaper(%s)", quit_cb)
        self._quit = quit_cb
        self._proc_info = []
        self._proc_lock = Lock()
        self._pending = (0, 0.0)
        self._retry = 0
        USE_PROCESS_POLLING = not POSIX or envbool("XPRA_USE_PROCESS_POLLING")
        if USE_PROCESS_POLLING:
            POLL_DELAY = envint("XPRA_POLL_DELAY", 2)
            log("using process polling every %s seconds", POLL_DELAY)
            GLib.timeout_add(POLL_DELAY * 1000, self.check)
        else:
            if not HAS_WAITID:
                log.warn("Warning: `os.waitid` is not available with this Python %s build", sys.version.split(" ", 1)[0])
                log.warn(" only the registered child processes will be reaped,")
                log.warn(" any other child process may be left as a zombie")
                log.warn(" please upgrade to Python 3.13 or later")
            # Check once after the mainloop is running, just in case the exit
            # conditions are satisfied before we even enter the main loop.
            # (Programming with unix the signal API sure is annoying.)

            def check_once() -> bool:
                # we're running in the main thread, so we can register the signal here:
                signal.signal(signal.SIGCHLD, self.sigchld)
                self.check()
                return False  # Only call once

            GLib.timeout_add(0, check_once)

    def cleanup(self) -> None:
        self.reap()
        self.poll()
        if self._retry:
            GLib.source_remove(self._retry)
            self._retry = 0
        with self._proc_lock:
            self._proc_info = []
        self._quit = None

    def add_pid(self, pid: int, name: str, command: str | Sequence[str], ignore=False, forget=False, callback=None) -> ProcInfo:
        # this method is used when we have a pid but not a Popen object
        process = PidPopen(pid)
        return self.add_process(process, name, command, ignore=ignore, forget=forget, callback=callback)

    def add_process(self, process, name: str, command: str | Sequence[str], ignore=False, forget=False, callback=None) -> ProcInfo:
        pid = process.pid
        if pid <= 0:
            raise RuntimeError(f"process {process} has no pid!")
        procinfo = ProcInfo()
        procinfo.sequence = sequence.increase()
        procinfo.pid = pid
        procinfo.pidfile = ""
        procinfo.pidinode = 0
        procinfo.name = name
        procinfo.command = command
        procinfo.ignore = ignore
        procinfo.forget = forget
        procinfo.callback = callback
        procinfo.process = process
        procinfo.returncode = None
        procinfo.dead = False
        procinfo.lock = Lock()
        log("add_process%s pid=%s", (process, name, command, ignore, forget, callback), pid)
        with self._proc_lock:
            self._proc_info.append(procinfo)
        # could have died already:
        if self._handle_death(procinfo):
            self.check_quit()
        return procinfo

    def poll(self) -> bool:
        # poll each process that is not dead yet:
        log("poll() procinfo list: %s", self._proc_info)
        died = False
        for procinfo in tuple(self._proc_info):
            process = procinfo.process
            if self._handle_death(procinfo):
                died = True
            elif process and not procinfo.dead and is_pending(process):
                self._schedule_retry()
        if died:
            self.check_quit()
        return True

    def set_quit_callback(self, cb: Callable) -> None:
        self._quit = cb

    def check(self) -> bool:
        self.poll()
        self.reap()
        # A waiter may have collected an exit after the first pending check.
        self.poll()
        return self.check_quit()

    def check_quit(self) -> bool:
        # see if we are meant to exit-with-children
        # see if we still have procinfos alive (and not meant to be ignored)
        watched = tuple(procinfo for procinfo in tuple(self._proc_info)
                        if not procinfo.ignore)
        alive = tuple(procinfo for procinfo in watched
                      if not procinfo.dead)
        cb = self._quit
        log("check() watched=%s, alive=%s, quit callback=%s", watched, alive, cb)
        if watched and not alive:
            if cb:
                self._quit = None
                cb()
            return False
        return True

    def sigchld(self, signum, frame) -> None:
        # we risk race conditions if doing anything in the signal handler,
        # better run in the main thread asap:
        GLib.idle_add(self._sigchld, signum, str(frame))

    def _sigchld(self, signum, frame_str) -> None:
        log("sigchld(%s, %s)", signum, frame_str)
        self.check()

    def get_proc_info(self, pid: int) -> ProcInfo | None:
        for proc_info in tuple(self._proc_info):
            if proc_info.pid == pid:
                return proc_info
        return None

    def add_dead_pid(self, pid: int) -> None:
        # find the procinfo for this pid:
        matches = [procinfo for procinfo in self._proc_info if procinfo.pid == pid and not procinfo.dead]
        log("add_dead_pid(%s) matches=%s", pid, matches)
        if not matches:
            # not one of ours? odd.
            return
        for procinfo in matches:
            self.add_dead_process(procinfo)

    def add_dead_process(self, procinfo: ProcInfo) -> None:
        log("add_dead_process(%s)", procinfo)
        if self._handle_death(procinfo):
            self.check_quit()
        elif not procinfo.dead:
            log.warn("Warning: process '%s' is still running", procinfo.name)

    def _handle_death(self, procinfo: ProcInfo) -> bool:
        # returns True if the process has just died and we handled it
        with procinfo.lock:
            process = procinfo.process
            if procinfo.dead or not process:
                return False
            procinfo.returncode = process.poll()
            if procinfo.returncode is None:
                return False
            procinfo.dead = True
            # clear the reference to the process to free up resources:
            procinfo.process = None
            cb, procinfo.callback = procinfo.callback, None
            if procinfo.pidfile and procinfo.pidinode:
                from xpra.util.pid import rm_pidfile
                rm_pidfile(procinfo.pidfile, procinfo.pidinode)
        log("handle_death(%s) returncode=%s, callback=%s", procinfo, procinfo.returncode, cb)
        if cb:
            GLib.idle_add(cb, process)
        if procinfo.ignore:
            log("child '%s' with pid %s has terminated (ignored)", procinfo.name, procinfo.pid)
        else:
            log.info("child '%s' with pid %s has terminated", procinfo.name, procinfo.pid)
        if procinfo.forget:
            try:
                with self._proc_lock:
                    self._proc_info.remove(procinfo)
            except ValueError:  # pragma: no cover
                log("failed to remove %s from proc info list", procinfo, exc_info=True)
        return True

    def reap(self) -> None:
        # reap all our dead children, including the ones that are not registered
        if not POSIX:
            return
        if not HAS_WAITID:
            # we can't find dead children without reaping them,
            # and their owner would then record a returncode of 0,
            # so we only reap registered processes, via `poll()`:
            return
        while True:
            try:
                # find a dead child without reaping it:
                info = os.waitid(os.P_ALL, 0, os.WEXITED | os.WNOHANG | os.WNOWAIT)
            except ChildProcessError:
                return
            log("reap() waitid=%s", info)
            if not info:
                return
            if not self._reap_pid(info.si_pid):
                self._schedule_retry()
                return

    def _schedule_retry(self) -> None:
        if not self._retry:
            self._retry = GLib.timeout_add(REAP_RETRY_DELAY * 1000, self._retry_reap)

    def _retry_reap(self) -> bool:
        self._retry = 0
        self.check()
        return False

    def _reap_pid(self, pid: int) -> bool:
        # returns True once the child is gone
        matches = tuple(procinfo for procinfo in tuple(self._proc_info) if procinfo.pid == pid and not procinfo.dead)
        if matches:
            for procinfo in matches:
                self._handle_death(procinfo)
            # `poll()` returns None when another thread is busy waiting for this process,
            # which will reap it:
            return any(procinfo.dead for procinfo in matches)
        # not registered (yet?): give the code that started it a chance to collect its exit status
        if self._pending[0] != pid:
            self._pending = (pid, monotonic())
        if monotonic() - self._pending[1] < UNKNOWN_CHILD_DELAY:
            return False
        self._pending = (0, 0.0)
        comm = get_comm(pid)
        log.warn(f"Warning: reaping child process {pid} {comm!r}")
        log.warn(f" which was not registered and has not been collected after {UNKNOWN_CHILD_DELAY} seconds")
        try:
            os.waitpid(pid, os.WNOHANG)
        except ChildProcessError:
            pass
        return True

    def get_info(self) -> dict[Any, Any]:
        iv = tuple(self._proc_info)
        info: dict[Any, Any] = {
            "children": {
                "total": len(iv),
                "dead": len(tuple(True for x in iv if x.dead)),
                "ignored": len(tuple(True for x in iv if x.ignore)),
            }
        }
        pi = sorted(self._proc_info, key=lambda x: x.sequence, reverse=True)
        cinfo: dict[int, Any] = info.setdefault("child", {})
        for procinfo in pi:
            d = {}
            for k in ("name", "command", "ignore", "forget", "returncode", "dead", "pid"):
                v = getattr(procinfo, k)
                if v is None:
                    continue
                d[k] = v
            cinfo[procinfo.sequence] = d
        return info


singleton: ChildReaper | None = None


def get_child_reaper() -> ChildReaper:
    global singleton
    if singleton is None:
        singleton = ChildReaper()
    assert singleton
    return singleton


def reaper_cleanup() -> None:
    s = singleton
    if s is not None:
        s.cleanup()
    # keep it around,
    # so we don't try to reinitialize it from the wrong thread
    # (signal requires the main thread)
    # singleton = None
