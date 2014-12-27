# This file is part of Xpra.
# Copyright (C) 2010-2014 Antoine Martin <antoine@devloop.org.uk>
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.


# This class is used by the posix server to ensure
# we reap the dead pids so that they don't become zombies,
# also used for implementing --exit-with-children

import os, sys
import signal
import gobject

from xpra.log import Logger
log = Logger("server", "util")

# use process polling with python versions older than 2.7 and 3.0, (because SIGCHLD support is broken)
# or when the user requests it with the env var:
BUGGY_PYTHON = sys.version_info<(2, 7) or sys.version_info[:2]==(3, 0)
USE_PROCESS_POLLING = os.name!="posix" or os.environ.get("XPRA_USE_PROCESS_POLLING")=="1" or BUGGY_PYTHON


# Note that this class has async subtleties -- e.g., it is possible for a
# child to exit and us to receive the SIGCHLD before our fork() returns (and
# thus before we even know the pid of the child).  So be careful:
class ChildReaper(object):
    #note: the quit callback will fire only once!
    def __init__(self, quit_cb):
        self._quit = quit_cb
        self._children_pids = {}
        self._dead_pids = set()
        self._ignored_pids = set()
        if USE_PROCESS_POLLING:
            POLL_DELAY = int(os.environ.get("XPRA_POLL_DELAY", 2))
            if BUGGY_PYTHON:
                log.warn("Warning: outdated/buggy version of Python: %s", ".".join(str(x) for x in sys.version_info))
                log.warn("switching to process polling every %s seconds to support 'exit-with-children'", POLL_DELAY)
            else:
                log("using process polling every %s seconds", POLL_DELAY)
            gobject.timeout_add(POLL_DELAY*1000, self.check)
        else:
            #with a less buggy python, we can just check the list of pids
            #whenever we get a SIGCHLD
            #however.. subprocess.Popen will no longer work as expected
            #see: http://bugs.python.org/issue9127
            #so we must ensure certain things that exec happen first:
            from xpra.version_util import get_platform_info
            get_platform_info()

            signal.signal(signal.SIGCHLD, self.sigchld)
            # Check once after the mainloop is running, just in case the exit
            # conditions are satisfied before we even enter the main loop.
            # (Programming with unix the signal API sure is annoying.)
            def check_once():
                self.check()
                return False # Only call once
            gobject.timeout_add(0, check_once)

    def add_process(self, process, name, command, ignore=False):
        process.command = command
        process.name = name
        assert process.pid>0
        self._children_pids[process.pid] = process
        if ignore:
            self._ignored_pids.add(process.pid)
        log("add_process(%s, %s, %s, %s) pid=%s", process, name, command, ignore, process.pid)

    def check(self):
        pids = set(self._children_pids.keys()) - self._ignored_pids
        log("check() pids=%s", pids)
        if pids:
            for pid, proc in self._children_pids.items():
                if proc.poll() is not None:
                    self.add_dead_pid(pid)
            log("check() pids=%s, dead_pids=%s", pids, self._dead_pids)
            if pids.issubset(self._dead_pids):
                cb = self._quit
                if cb:
                    self._quit = None
                    cb()
                return False
        return True

    def sigchld(self, signum, frame):
        log("sigchld(%s, %s)", signum, frame)
        self.reap()

    def add_dead_pid(self, pid):
        log("add_dead_pid(%s)", pid)
        if pid not in self._dead_pids:
            proc = self._children_pids.get(pid)
            if proc:
                if pid in self._ignored_pids:
                    log("child '%s' with pid %s has terminated (ignored)", proc.name, pid)
                else:
                    log.info("child '%s' with pid %s has terminated", proc.name, pid)
            self._dead_pids.add(pid)
            self.check()

    def reap(self):
        while True:
            try:
                pid, _ = os.waitpid(-1, os.WNOHANG)
            except OSError:
                break
            log("reap() waitpid=%s", pid)
            if pid == 0:
                break
            self.add_dead_pid(pid)

    def get_info(self):
        d = dict(self._children_pids)
        info = {"children"          : len(d),
                "children.dead"     : len(self._dead_pids),
                "children.ignored"  : len(self._ignored_pids)}
        for i, pid in enumerate(sorted(d.keys())):
            proc = d[pid]
            info["child[%i].live" % i]  = pid not in self._dead_pids
            info["child[%i].pid" % i]   = pid
            info["child[%i].command" % i]   = proc.command
            info["child[%i].ignored" % i] = pid in self._ignored_pids
        return info
