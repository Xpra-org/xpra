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
from typing import Any
from collections.abc import Callable, Sequence

from xpra.util.env import envint, envbool
from xpra.os_util import POSIX, gi_import
from xpra.log import Logger

GLib = gi_import("GLib")
log = Logger("server", "util", "exec")


class ProcInfo:
    __slots__ = (
        "pid", "pidfile", "pidinode",
        "name", "command", "ignore",
        "forget", "dead", "returncode",
        "callback", "process",
    )
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


# Note that this class has async subtleties -- e.g., it is possible for a
# child to exit and us to receive the SIGCHLD before our fork() returns (and
# thus before we even know the pid of the child).  So be careful:
# We can also end up with multiple procinfo structures with the same pid,
# and that should be fine too
#
# WNOHANG is a tricky beast, see:
# https://github.com/gevent/gevent/issues/622
class ChildReaper:
    __slots__ = ("_quit", "_proc_info")

    # note: the quit callback will fire only once!

    def __init__(self, quit_cb=None):
        log("ChildReaper(%s)", quit_cb)
        self._quit = quit_cb
        self._proc_info = []
        USE_PROCESS_POLLING = not POSIX or envbool("XPRA_USE_PROCESS_POLLING")
        if USE_PROCESS_POLLING:
            POLL_DELAY = envint("XPRA_POLL_DELAY", 2)
            log("using process polling every %s seconds", POLL_DELAY)
            GLib.timeout_add(POLL_DELAY * 1000, self.check)
        else:
            signal.signal(signal.SIGCHLD, self.sigchld)

            # Check once after the mainloop is running, just in case the exit
            # conditions are satisfied before we even enter the main loop.
            # (Programming with unix the signal API sure is annoying.)

            def check_once():
                self.check()
                return False  # Only call once

            GLib.timeout_add(0, check_once)

    def cleanup(self) -> None:
        self.reap()
        self.poll()
        self._proc_info = []
        self._quit = None

    def add_process(self, process, name: str, command: str | Sequence[str], ignore=False, forget=False, callback=None) -> ProcInfo:
        pid = process.pid
        if pid <= 0:
            raise RuntimeError(f"process {process} has no pid!")
        procinfo = ProcInfo()
        procinfo.pid = pid
        procinfo.pidfile = ""
        procinfo.pidinode = 0
        procinfo.name = name
        procinfo.command = command
        procinfo.ignore = ignore
        procinfo.forget = forget
        procinfo.callback = callback
        procinfo.process = process
        procinfo.returncode = process.poll()
        procinfo.dead = procinfo.returncode is not None
        log("add_process%s pid=%s", (process, name, command, ignore, forget, callback), pid)
        # could have died already:
        self._proc_info.append(procinfo)
        if procinfo.dead:
            self.add_dead_process(procinfo)
        return procinfo

    def poll(self) -> bool:
        # poll each process that is not dead yet:
        log("poll() procinfo list: %s", self._proc_info)
        for procinfo in tuple(self._proc_info):
            process = procinfo.process
            if not procinfo.dead and process and process.poll() is not None:
                self.add_dead_process(procinfo)
        return True

    def set_quit_callback(self, cb: Callable) -> None:
        self._quit = cb

    def check(self) -> bool:
        # see if we are meant to exit-with-children
        # see if we still have procinfos alive (and not meant to be ignored)
        self.poll()
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
        self.reap()

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
        process = procinfo.process
        if procinfo.dead or not process:
            return
        procinfo.returncode = process.poll()
        procinfo.dead = procinfo.returncode is not None
        cb = procinfo.callback
        log("add_dead_process returncode=%s, dead=%s, callback=%s", procinfo.returncode, procinfo.dead, cb)
        if not procinfo.dead:
            log.warn("Warning: process '%s' is still running", procinfo.name)
            return
        if process and cb:
            procinfo.callback = None
            GLib.idle_add(cb, process)
        if procinfo.pidfile and procinfo.pidinode:
            from xpra.server.util import rm_pidfile
            rm_pidfile(procinfo.pidfile, procinfo.pidinode)
        # once it's dead, clear the reference to the process:
        # this should free up some resources
        # and also help to ensure we don't end up here again
        procinfo.process = None
        if procinfo.ignore:
            log("child '%s' with pid %s has terminated (ignored)", procinfo.name, procinfo.pid)
        else:
            log.info("child '%s' with pid %s has terminated", procinfo.name, procinfo.pid)
        if procinfo.forget:
            # forget it:
            try:
                self._proc_info.remove(procinfo)
            except ValueError:  # pragma: no cover
                log("failed to remove %s from proc info list", procinfo, exc_info=True)
        log("updated procinfo=%s", procinfo)
        self.check()

    def reap(self) -> None:
        self.poll()
        while POSIX:
            log("reap() calling os.waitpid%s", (-1, "WNOHANG"))
            try:
                pid = os.waitpid(-1, os.WNOHANG)[0]
            except OSError:
                break
            log("reap() waitpid=%s", pid)
            if pid == 0:
                break
            self.add_dead_pid(pid)

    def get_info(self) -> dict[Any, Any]:
        iv = tuple(self._proc_info)
        info: dict[Any, Any] = {
            "children": {
                "total": len(iv),
                "dead": len(tuple(True for x in iv if x.dead)),
                "ignored": len(tuple(True for x in iv if x.ignore)),
            }
        }
        pi = sorted(self._proc_info, key=lambda x: x.pid, reverse=True)
        cinfo: dict[int, Any] = info.setdefault("child", {})
        for i, procinfo in enumerate(pi):
            d = {}
            for k in ("name", "command", "ignore", "forget", "returncode", "dead", "pid"):
                v = getattr(procinfo, k)
                if v is None:
                    continue
                d[k] = v
            cinfo[i] = d
        return info


singleton: ChildReaper | None = None


def getChildReaper() -> ChildReaper:
    global singleton
    if singleton is None:
        singleton = ChildReaper()
    return singleton


def reaper_cleanup() -> None:
    s = singleton
    if s is not None:
        s.cleanup()
    # keep it around,
    # so we don't try to reinitialize it from the wrong thread
    # (signal requires the main thread)
    # singleton = None
