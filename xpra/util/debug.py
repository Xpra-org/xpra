# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.
from time import sleep
from typing import Callable

from xpra.common import noop
from xpra.util.env import envbool, envint

CPUINFO = envbool("XPRA_CPUINFO", False)
DETECT_MEMLEAKS = envint("XPRA_DETECT_MEMLEAKS", 0)
DETECT_FDLEAKS = envbool("XPRA_DETECT_FDLEAKS", False)


def init_leak_detection(exit_condition: Callable[[], bool] = noop):
    print_memleaks = None
    if DETECT_MEMLEAKS:
        from xpra.util.pysystem import detect_leaks
        print_memleaks = detect_leaks()
        if bool(print_memleaks):
            def leak_thread() -> None:
                while not exit_condition():
                    print_memleaks()
                    sleep(DETECT_MEMLEAKS)

            from xpra.util.thread import start_thread  # pylint: disable=import-outside-toplevel
            start_thread(leak_thread, "leak thread", daemon=True)

    if DETECT_FDLEAKS:
        from xpra.log import Logger
        log = Logger("util")
        from xpra.util.io import livefds
        saved_fds = [livefds(), ]

        def print_fds() -> bool:
            fds = livefds()
            newfds = fds - saved_fds[0]
            saved_fds[0] = fds
            log.info("print_fds() new fds=%s (total=%s)", newfds, len(fds))
            return True

        from xpra.os_util import gi_import
        GLib = gi_import("GLib")
        GLib.timeout_add(10, print_fds)

    return print_memleaks
