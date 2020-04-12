# This file is part of Xpra.
# Copyright (C) 2012-2020 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

#legacy compatibility file

import sys
import signal

from xpra.util import dump_all_frames, dump_gc_frames
from xpra.os_util import SIGNAMES, POSIX, get_util_logger


_glib_unix_signals = {}
def register_os_signals(callback, commandtype="", signals=(signal.SIGINT, signal.SIGTERM)):
    from gi.repository import GLib
    def handle_signal(signum):
        try:
            sys.stderr.write("\n")
            sys.stderr.flush()
            cstr = ""
            if commandtype:
                cstr = commandtype+" "
            get_util_logger().info("%sgot signal %s", cstr, SIGNAMES.get(signum, signum))
        except OSError:
            pass
        callback(signum)
        return True
    def os_signal(signum, _frame):
        GLib.idle_add(handle_signal, signum)
        return True
    for signum in signals:
        if POSIX:
            #replace the previous definition if we had one:
            global _glib_unix_signals
            current = _glib_unix_signals.get(signum, None)
            if current:
                GLib.source_remove(current)
            source_id = GLib.unix_signal_add(GLib.PRIORITY_HIGH, signum, handle_signal, signum)
            _glib_unix_signals[signum] = source_id
        else:
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
