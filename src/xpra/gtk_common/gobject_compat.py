# This file is part of Xpra.
# Copyright (C) 2012-2019 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

#legacy compatibility file

import sys


_glib_unix_signals = {}
def register_os_signals(callback):
    from xpra.os_util import SIGNAMES, POSIX, get_util_logger
    from gi.repository import GLib
    import signal
    def handle_signal(signum):
        try:
            sys.stderr.write("\n")
            sys.stderr.flush()
            get_util_logger().info("got signal %s", SIGNAMES.get(signum, signum))
        except OSError:
            pass
        callback(signum)
    def os_signal(signum, _frame):
        GLib.idle_add(handle_signal, signum)
    for signum in (signal.SIGINT, signal.SIGTERM):
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
