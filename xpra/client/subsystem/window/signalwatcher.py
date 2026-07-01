# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import errno
import signal
from subprocess import Popen, PIPE, STDOUT, TimeoutExpired
from collections.abc import Sequence

from xpra.common import noerr
from xpra.platform.paths import get_python_execfile_command
from xpra.util.io import find_libexec_command
from xpra.util.str_fn import std
from xpra.os_util import OSX, POSIX, gi_import
from xpra.util.system import stop_proc
from xpra.util.objects import typedict
from xpra.util.env import envbool
from xpra.client.base.stub import StubClientMixin
from xpra.log import Logger

log = Logger("window", "exec")

GLib = gi_import("GLib")


def find_signal_watcher_command() -> str:
    if not envbool("XPRA_SIGNAL_WATCHER", POSIX and not OSX):
        return ""
    cmd = os.environ.get("XPRA_SIGNAL_WATCHER_COMMAND", "xpra_signal_listener")
    return find_libexec_command(cmd)


SIGNAL_WATCHER_COMMAND = find_signal_watcher_command()


def kill_signalwatcher(proc) -> None:
    clean_signalwatcher(proc)
    exit_code = proc.poll()
    log(f"kill_signalwatcher({proc}) {exit_code=}")
    if exit_code is not None:
        return
    try:
        stdin = proc.stdin
        if stdin:
            stdin.write(b"exit\n")
            stdin.flush()
            stdin.close()
    except OSError:
        log.warn("Warning: failed to tell the signal watcher to exit", exc_info=True)
    if proc.poll() is not None:
        return
    stop_proc(proc, "signalwatcher")
    try:
        proc.wait(0.01)
    except TimeoutExpired:
        try:
            os.kill(proc.pid, signal.SIGKILL)
        except OSError as e:
            if e.errno != errno.ESRCH:
                log.warn("Warning: failed to tell the signal watcher to exit", exc_info=True)


def clean_signalwatcher(proc) -> None:
    stdout_io_watch = proc.stdout_io_watch
    if stdout_io_watch:
        proc.stdout_io_watch = 0
        GLib.source_remove(stdout_io_watch)
    stdout = proc.stdout
    if stdout:
        log(f"stdout={stdout}")
        noerr(stdout.close)
    stderr = proc.stderr
    if stderr:
        noerr(stderr.close)


class WindowSignalWatcher(StubClientMixin):
    """
    Adds ability to run a signal_watcher command for each window.
    """

    def __init__(self):
        self._pid_to_signalwatcher = {}
        self._signalwatcher_to_wids = {}
        self.server_window_signals: Sequence[str] = ()

    def cleanup(self) -> None:
        self.kill_all_signalwatchers()

    def parse_server_capabilities(self, c: typedict) -> bool:
        self.server_window_signals = c.strtupleget("window.signals")
        return True

    def kill_all_signalwatchers(self) -> None:
        # signal watchers should have been killed in destroy_window(),
        # make sure we don't leave any behind:
        for signalwatcher in tuple(self._signalwatcher_to_wids.keys()):
            kill_signalwatcher(signalwatcher)

    ######################################################################
    # listen for process signals using a watcher process:
    def assign_signal_watcher_pid(self, wid: int, pid: int, title="") -> int:
        if not SIGNAL_WATCHER_COMMAND or not pid:
            return 0
        proc = self._pid_to_signalwatcher.get(pid)
        if proc is None or proc.poll():
            from xpra.util.child_reaper import get_child_reaper
            if not title:
                title = str(pid)
            cmd = get_python_execfile_command() + [SIGNAL_WATCHER_COMMAND] + [f"signal watcher for {std(title)}"]
            log(f"assign_signal_watcher_pid({wid:#x}, {pid}) starting {cmd}")
            try:
                proc = Popen(cmd,
                             stdin=PIPE, stdout=PIPE, stderr=STDOUT,
                             start_new_session=True)
            except OSError as e:
                log("assign_signal_watcher_pid(%#x, %s)", wid, pid, exc_info=True)
                log.error("Error: cannot execute signal listener")
                log.estr(e)
                proc = None
            if proc and proc.poll() is None:
                proc.stdout_io_watch = 0

                def watcher_terminated(*args):
                    # watcher process terminated, remove io watch:
                    # this may be redundant since we also return False from signal_watcher_event
                    log("watcher_terminated%s", args)
                    clean_signalwatcher(proc)

                get_child_reaper().add_process(proc, "signal listener for remote process %s" % pid,
                                               command="xpra_signal_listener", ignore=True, forget=True,
                                               callback=watcher_terminated)
                log("using watcher pid=%i for server pid=%i", proc.pid, pid)
                self._pid_to_signalwatcher[pid] = proc
                ioc = GLib.IOCondition
                proc.stdout_io_watch = GLib.io_add_watch(proc.stdout,
                                                         GLib.PRIORITY_DEFAULT, ioc.IN | ioc.HUP | ioc.ERR,
                                                         self.signal_watcher_event, proc, pid, wid)
        if proc:
            self._signalwatcher_to_wids.setdefault(proc, []).append(wid)
            return proc.pid
        return 0

    def signal_watcher_event(self, fd, cb_condition, proc, pid: int, wid: int) -> bool:
        log("signal_watcher_event%s", (fd, cb_condition, proc, pid, wid))
        GLib = gi_import("GLib")
        if cb_condition in (GLib.IOCondition.HUP, GLib.IOCondition.ERR):
            kill_signalwatcher(proc)
            proc.stdout_io_watch = None
            return False
        if proc.stdout_io_watch is None:
            # no longer watched
            return False
        if cb_condition == GLib.IOCondition.IN:
            try:
                signame = proc.stdout.readline().decode("latin1").strip("\n\r")
                log("signal_watcher_event: %s", signame)
                if signame:
                    if signame in self.server_window_signals:
                        self.send("window-signal", wid, signame)
                    else:
                        log(f"Warning: signal {signame!r} cannot be forwarded to this server")
            except Exception as e:
                log.error("signal_watcher_event%s", (fd, cb_condition, proc, pid, wid), exc_info=True)
                log.error("Error: processing signal watcher output for pid %i of window %#x", pid, wid)
                log.estr(e)
        if proc.poll():
            # watcher ended, stop watching its stdout
            proc.stdout_io_watch = None
            return False
        return True
