# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

"""
Workaround for https://github.com/Xpra-org/xpra/issues/5044

PyGObject versions older than 3.44.2 free callback closures using `g_callable_info_free_closure()`,
which is a no-op with GObject-Introspection 1.72 onwards (ie: Debian Bookworm).
So every call to `GLib.idle_add` leaks an executable libffi closure.

Instead, we route `GLib.idle_add` through a single persistent custom `GLib.Source`:
its `prepare` / `check` / `dispatch` methods are called from PyGObject's C code
without creating any new closures.
"""

import os
from threading import Lock
from typing import Any
from collections.abc import Callable

from xpra.util.env import envbool

# GLib allocates source ids incrementally from 1, stay well clear of those:
FIRST_ID = 2 ** 32 - 1
LAST_ID = 2 ** 31


def get_env_value() -> bool | None:
    value = os.environ.get("XPRA_GLIB_IDLE_QUEUE", "")
    if not value:
        return None
    return envbool("XPRA_GLIB_IDLE_QUEUE")


def has_create_closure() -> bool:
    # `g_callable_info_create_closure` was added in GObject-Introspection 1.72,
    # at the same time as `g_callable_info_free_closure` stopped freeing anything.
    # PyGObject is already loaded, so this finds the library it is using without touching the filesystem:
    from ctypes import CDLL
    for name in ("libgirepository-1.0.so.1", "libgirepository-1.0-1.dll", "libgirepository-1.0.1.dylib"):
        try:
            lib = CDLL(name)
        except OSError:
            continue
        return hasattr(lib, "g_callable_info_create_closure")
    return False


def needs_idle_queue(gi) -> bool:
    env = get_env_value()
    if env is not None:
        return env
    # PyGObject 3.44.2 switched to `g_callable_info_create_closure` / `g_callable_info_destroy_closure`:
    if tuple(gi.version_info) >= (3, 44, 2):
        return False
    return has_create_closure()


def install(GLib) -> None:
    if getattr(GLib, "_xpra_idle_queue", None):
        return
    import gi
    if not needs_idle_queue(gi):
        return

    from xpra.log import Logger
    log = Logger("util")

    glib_idle_add = GLib.idle_add
    glib_source_remove = GLib.source_remove

    class IdleQueueSource(GLib.Source):

        def __init__(self):
            super().__init__()
            self.set_priority(GLib.PRIORITY_DEFAULT_IDLE)
            self.lock = Lock()
            self.counter = FIRST_ID
            self.pending: dict[int, tuple[Callable, tuple]] = {}

        def prepare(self):
            return bool(self.pending), -1

        def check(self):
            return bool(self.pending)

        def dispatch(self, _callback, _args) -> bool:
            with self.lock:
                calls = tuple(self.pending.items())
            for sid, (fn, args) in calls:
                if sid not in self.pending:
                    # removed by one of the previous callbacks
                    continue
                try:
                    repeat = fn(*args)
                except Exception:
                    log.error("Error calling %s%s", fn, args, exc_info=True)
                    repeat = False
                if not repeat:
                    with self.lock:
                        self.pending.pop(sid, None)
            return GLib.SOURCE_CONTINUE

        def add(self, fn: Callable, args: tuple) -> int:
            with self.lock:
                self.counter -= 1
                if self.counter < LAST_ID:
                    self.counter = FIRST_ID
                sid = self.counter
                wakeup = not self.pending
                self.pending[sid] = (fn, args)
            if wakeup:
                # we may be called from a different thread:
                GLib.MainContext.default().wakeup()
            return sid

        def remove(self, sid: int) -> bool:
            with self.lock:
                return self.pending.pop(sid, None) is not None

    source = IdleQueueSource()
    source.attach(GLib.MainContext.default())

    def destroy_source() -> None:
        # same as `Source.__del__`, which would otherwise run during interpreter shutdown
        # and fail with "ImportError: sys.meta_path is None":
        source.destroy()
        source._clear_boxed()
        delattr(source, "__pygi_custom_source")

    import atexit
    atexit.register(destroy_source)

    def idle_add(function: Callable, *user_data: Any, **kwargs) -> int:
        priority = kwargs.get("priority", GLib.PRIORITY_DEFAULT_IDLE)
        if priority != GLib.PRIORITY_DEFAULT_IDLE:
            return glib_idle_add(function, *user_data, **kwargs)
        return source.add(function, user_data)

    def source_remove(sid: int) -> bool:
        if sid >= LAST_ID and source.remove(sid):
            return True
        return glib_source_remove(sid)

    GLib._xpra_idle_queue = source
    GLib.idle_add = idle_add
    GLib.source_remove = source_remove
    log.warn("Warning: PyGObject %s leaks memory with this version of GObject-Introspection", gi.__version__)
    log.warn(" every GLib callback leaks an executable closure, PyGObject 3.44.2 or later fixes this")
    log.warn(" xpra will use a workaround for `GLib.idle_add`, but other callbacks still leak")
    log.warn(" see https://github.com/Xpra-org/xpra/issues/5044")
