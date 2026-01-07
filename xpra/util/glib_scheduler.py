# This file is part of Xpra.
# Copyright (C) 2013 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from collections.abc import Callable

from xpra.util.objects import Scheduler
from xpra.os_util import gi_import

GLib = gi_import("GLib")


class GLibScheduler(Scheduler):

    def idle_add(self, fn: Callable, *args, **kwargs) -> int:
        return GLib.idle_add(fn, *args, **kwargs)

    def timeout_add(self, timeout, fn: Callable, *args, **kwargs) -> int:
        return GLib.timeout_add(timeout, fn, *args, **kwargs)

    def source_remove(self, tid: int) -> None:
        GLib.source_remove(tid)
