# This file is part of Xpra.
# Copyright (C) 2010-2017 Antoine Martin <antoine@devloop.org.uk>
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.


# This class is used by the posix server to ensure
# we reap the dead pids so that they don't become zombies,
# also used for implementing --exit-with-children

import os
import signal

from xpra.util import envint, envbool
from xpra.log import Logger
log = Logger("server", "util")


USE_PROCESS_POLLING = os.name!="posix" or envbool("XPRA_USE_PROCESS_POLLING")
POLL_DELAY = envint("XPRA_POLL_DELAY", 2)


singleton = None
def getChildReaper():
    global singleton
    if singleton is None:
        singleton = ChildReaper()
    return singleton


def reaper_cleanup():
    global singleton
    s = singleton
    if not s:
        return
    s.reap()
    s.poll()
    singleton = None


class ProcInfo(object):
    def __repr__(self):
        return "ProcInfo(%s)" % self.__dict__


# Note that this class has async subtleties -- e.g., it is possible for a
# child to exit and us to receive the SIGCHLD before our fork() returns (and
# thus before we even know the pid of the child).  So be careful:
# We can also end up with multiple procinfo structures with the same pid,
# and that should be fine too
#
# WNOHANG is a tricky beast, see:
# https://github.com/gevent/gevent/issues/622
class ChildReaper(object):
    #note: the quit callback will fire only once!
    def __init__(self, quit_cb=None):
        log("ChildReaper(%s)", quit_cb)
        from xpra.gtk_common.gobject_compat import import_glib
        self.glib = import_glib()
        self._quit = quit_cb
        self._proc_info = []
        if USE_PROCESS_POLLING:
            log("using process polling every %s seconds", POLL_DELAY)
            self.glib.timeout_add(POLL_DELAY*1000, self.poll)
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
            self.glib.timeout_add(0, check_once)

    def add_process(self, process, name, command, ignore=False, forget=False, callback=None):
        pid = process.pid
        assert pid>0, "process has no pid!"
        procinfo = ProcInfo()
        procinfo.pid = pid
        procinfo.name = name
        procinfo.command = command
        procinfo.ignore = ignore
        procinfo.forget = forget
        procinfo.callback = callback
        procinfo.process = process
        procinfo.returncode = process.poll()
        procinfo.dead = False
        log("add_process(%s, %s, %s, %s, %s) pid=%s", process, name, command, ignore, forget, pid)
        #could have died already:
        self._proc_info.append(procinfo)
        if procinfo.returncode is not None:
            self.add_dead_process(procinfo)
        return procinfo

    def poll(self):
        #poll each process that is not dead yet:
        log("poll() procinfo list: %s", self._proc_info)
        for procinfo in list(self._proc_info):
            process = procinfo.process
            if not procinfo.dead and process and process.poll() is not None:
                self.add_dead_process(procinfo)
        return True

    def set_quit_callback(self, cb):
        self._quit = cb

    def check(self):
        #see if we are meant to exit-with-children
        #see if we still have procinfos alive (and not meant to be ignored)
        self.poll()
        alive = [procinfo for procinfo in list(self._proc_info) if (not procinfo.ignore and not procinfo.dead)]
        cb = self._quit
        log("check() alive=%s, quit callback=%s", alive, cb)
        if len(alive)==0:
            if cb:
                self._quit = None
                cb()
            return False
        return True

    def sigchld(self, signum, frame):
        self.glib.idle_add(log, "sigchld(%s, %s)", signum, frame)
        self.glib.idle_add(self.reap)

    def add_dead_pid(self, pid):
        #find the procinfo for this pid:
        matches = [procinfo for procinfo in self._proc_info if procinfo.pid==pid and not procinfo.dead]
        log("add_dead_pid(%s) matches=%s", pid, matches)
        if not matches:
            #not one of ours? odd.
            return
        for procinfo in matches:
            self.add_dead_process(procinfo)

    def add_dead_process(self, procinfo):
        log("add_dead_process(%s)", procinfo)
        process = procinfo.process
        if process:
            procinfo.returncode = process.poll()
            procinfo.dead = procinfo.returncode is not None
            cb = procinfo.callback
            log("add_dead_process returncode=%s, dead=%s, callback=%s", procinfo.returncode, procinfo.dead, cb)
            if procinfo.dead and procinfo.process and cb:
                procinfo.callback = None
                cb(procinfo.process)
            if procinfo.dead:
                #once it's dead, clear the reference to the process:
                #this should free up some resources
                #and ensure we don't end up here again
                procinfo.process = None
                if procinfo.ignore:
                    log("child '%s' with pid %s has terminated (ignored)", procinfo.name, procinfo.pid)
                else:
                    log.info("child '%s' with pid %s has terminated", procinfo.name, procinfo.pid)
        if procinfo.dead and procinfo.forget:
            #forget it:
            try:
                self._proc_info.remove(procinfo)
            except:
                log("failed to remove %s from proc info list", procinfo, exc_info=True)
        log("updated procinfo=%s", procinfo)
        if procinfo.dead:
            self.check()

    def reap(self):
        self.poll()
        while os.name=="posix":
            log("reap() calling os.waitpid%s", (-1, "WNOHANG"))
            try:
                pid, _ = os.waitpid(-1, os.WNOHANG)
            except OSError:
                break
            log("reap() waitpid=%s", pid)
            if pid == 0:
                break
            self.add_dead_pid(pid)

    def get_info(self):
        iv = list(self._proc_info)
        info = {
                "children"  : {
                               "total"      : len(iv),
                               "dead"       : len([x for x in iv if x.dead]),
                               "ignored"    : len([x for x in iv if x.ignore]),
                               }
                }
        pi = sorted(self._proc_info, key=lambda x: x.pid, reverse=True)
        cinfo = {}
        for i, procinfo in enumerate(pi):
            d = {}
            for k in ("name", "command", "ignore", "forget", "returncode", "dead", "pid"):
                v = getattr(procinfo, k)
                if v is None:
                    continue
                d[k] = v
            cinfo[i] = d
        info["child"] = cinfo
        return info
