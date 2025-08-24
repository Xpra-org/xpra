# This file is part of Xpra.
# Copyright (C) 2015 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from typing import Any
from collections.abc import Callable

from xpra.os_util import gi_import
from xpra.log import Logger

log = Logger("util")


class SignalEmitter:
    """
    Emulates a subset of GObject signal functions.
    Enough so that subsystems can assume that these functions exist
    by inheriting from this class.
    This allows us to exercise more functionality when running the unit tests.
    """

    def __init__(self):
        self._signal_callbacks: dict[str, list[tuple[Callable, list[Any]]]] = {}

    def connect(self, signal: str, cb: Callable, *args) -> None:
        """ gobject style signal registration """
        log("connect(%s, %s, %s)", signal, cb, args)
        self._signal_callbacks.setdefault(signal, []).append((cb, list(args)))

    def emit(self, signal: str, *extra_args):
        log("%s.emit(%s, %s)", self, signal, extra_args)
        self._fire_callback(signal, extra_args)

    def _fire_callback(self, signal_name: str, extra_args=()) -> None:
        callbacks = self._signal_callbacks.get(signal_name, ())
        log("firing callback for '%s': %s", signal_name, callbacks)
        if not callbacks:
            return
        GLib = gi_import("GLib")
        for cb, args in callbacks:
            with log.trap_error(f"Error processing callback {cb} for {signal_name} packet"):
                all_args = list(args) + list(extra_args)
                GLib.idle_add(cb, self, *all_args)
