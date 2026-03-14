# This file is part of Xpra.
# Copyright (C) 2012 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

"""
Intercepting thread creation

These wrapper functions are here so that we can more easily intercept
the creation of all daemon threads and inject some code.

This is used by the `pycallgraph` test wrapper.
(this is cleaner than overriding the threading module directly
 as only our code will be affected)
"""

import threading
from threading import Thread, current_thread, main_thread
from collections.abc import Callable

from xpra.util.env import envbool

UI_THREAD_CHECK = envbool("XPRA_UI_THREAD_CHECK", True)


def make_thread(target: Callable, name: str, daemon: bool = False, args=()) -> Thread:
    t = Thread(target=target, name=name, args=args)
    t.daemon = daemon
    return t


def start_thread(target: Callable, name: str, daemon: bool = False, args=()) -> Thread:
    t = make_thread(target, name, daemon, args=args)
    t.start()
    return t


def is_main_thread() -> bool:
    return current_thread() is main_thread()


def check_main_thread() -> None:
    if UI_THREAD_CHECK and not is_main_thread():
        ct = threading.current_thread()
        raise RuntimeError(f"called from {ct.name!r} instead of main thread")
