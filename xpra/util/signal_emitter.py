# This file is part of Xpra.
# Copyright (C) 2015 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from typing import Any
from collections.abc import Callable

from xpra.os_util import gi_import
from xpra.log import Logger

log = Logger("util", "events")


class SignalEmitter:
    """
    Emulates a subset of GObject signal functions.
    Enough so that subsystems can assume that these functions exist
    by inheriting from this class.
    This allows us to exercise more functionality when running the unit tests.
    """
    # This class must not add any instance layout of its own: the servers
    # combine it (via `GLibServer` -> `ServerBase`) with `GObject.GObject`,
    # ie: `DesktopServerBase(GObject.GObject, ServerBase)`, and a C type
    # cannot be fused with a Python class that declares real slots
    # ("multiple bases have instance lay-out conflict").
    # So the state it uses - `_signal_callbacks`, and the optional `main_loop`
    # read by `get_main_loop` - is declared by the subclasses that want to be
    # strictly slotted (`StubSubsystem`, `StubClientSubsystem`); subclasses
    # that keep a `__dict__` (`GLibServer`, `StubClientConnection`, ...) get
    # them from there. As a result this class cannot be instantiated directly.
    __slots__ = ()
    __signals__ = ()

    def __init__(self):
        self._signal_callbacks: dict[str, list[tuple[Callable, list[Any]]]] = {}

    def connect(self, signal: str, cb: Callable, *args) -> None:
        """ gobject style signal registration """
        self._verify_signal(signal)
        log("connect(%s, %s, %s)", signal, cb, args)
        self._signal_callbacks.setdefault(signal, []).append((cb, list(args)))

    def emit(self, signal: str, *extra_args):
        self._verify_signal(signal)
        log("%s.emit(%s, %s)", self, signal, extra_args)
        self._fire_callback(signal, extra_args)

    def _verify_signal(self, signal: str) -> None:
        # catches typos and signals that were renamed/removed on one side only:
        # every class using a signal name should declare it in its own `__signals__`.
        if signal not in self.__signals__:
            log.warn("Warning: %r is not a declared signal of %s", signal, type(self).__name__)

    def get_main_loop(self):
        return getattr(self, "main_loop", None)

    def _should_call_direct(self) -> bool:
        """ Return True when callbacks can be invoked immediately. """
        main_loop = self.get_main_loop()
        if main_loop is None:
            return True
        if not main_loop.is_running():
            return True
        return main_loop.get_context().is_owner()

    def _fire_callback(self, signal_name: str, extra_args=()) -> None:
        callbacks = self._signal_callbacks.get(signal_name, ())
        log("firing callback for '%s': %s", signal_name, callbacks)
        if not callbacks:
            return
        GLib = gi_import("GLib")
        call_direct = self._should_call_direct()
        for cb, args in callbacks:
            with log.trap_error(f"Error processing callback {cb} for {signal_name} packet"):
                all_args = [self] + list(args) + list(extra_args)
                if call_direct:
                    cb(*all_args)
                else:
                    GLib.idle_add(cb, *all_args)
