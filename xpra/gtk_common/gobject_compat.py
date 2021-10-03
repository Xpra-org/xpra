# This file is part of Xpra.
# Copyright (C) 2012-2021 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

#legacy compatibility file

import sys
import signal

from xpra.util import dump_all_frames, dump_gc_frames
from xpra.os_util import SIGNAMES, POSIX, get_util_logger


_glib_unix_signals = {}
def register_os_signals(callback, commandtype="", signals=(signal.SIGINT, signal.SIGTERM)):
    for signum in signals:
        register_os_signal(callback, commandtype, signum)

def register_os_signal(callback, commandtype="", signum=signal.SIGINT):
    from gi.repository import GLib  #pylint: disable=import-outside-toplevel
    signame = SIGNAMES.get(signum, str(signum))
    def write_signal():
        if commandtype is None:
            return
        try:
            sys.stderr.write("\n")
            sys.stderr.flush()
            cstr = ""
            if commandtype:
                cstr = commandtype+" "
            get_util_logger().info("%sgot signal %s", cstr, signame)
        except OSError:
            pass
    def do_handle_signal():
        callback(signum)
    if POSIX:
        #replace the previous definition if we had one:
        global _glib_unix_signals
        current = _glib_unix_signals.get(signum, None)
        if current:
            GLib.source_remove(current)
        def handle_signal(_signum):
            write_signal()
            do_handle_signal()
            return True
        source_id = GLib.unix_signal_add(GLib.PRIORITY_HIGH, signum, handle_signal, signum)
        _glib_unix_signals[signum] = source_id
    else:
        def os_signal(_signum, _frame):
            write_signal()
            GLib.idle_add(do_handle_signal)
        signal.signal(signum, os_signal)

def register_SIGUSR_signals(commandtype="Server"):
    if not POSIX:
        return
    log = get_util_logger()
    def sigusr1(_sig):
        log.info("SIGUSR1")
        dump_all_frames(log.info)
        return True
    def sigusr2(*_args):
        log.info("SIGUSR2")
        dump_gc_frames(log.info)
        return True
    register_os_signals(sigusr1, commandtype, (signal.SIGUSR1, ))
    register_os_signals(sigusr2, commandtype, (signal.SIGUSR2, ))


def install_signal_handlers(sstr, signal_handler):
    #only register the glib signal handler
    #once the main loop is running,
    #before that we just trigger a KeyboardInterrupt
    def do_install_signal_handlers():
        register_os_signals(signal_handler, sstr)
        register_SIGUSR_signals(sstr)
    from gi.repository import GLib  #pylint: disable=import-outside-toplevel
    GLib.idle_add(do_install_signal_handlers)
