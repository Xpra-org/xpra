#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Sam Estep <sam@samestep.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import sys
import ctypes
import unittest
from itertools import pairwise
from threading import Thread, Event
from time import monotonic, sleep

from xpra.os_util import POSIX, OSX
from xpra.util.io import pollwait
from xpra.util.env import OSEnvContext
from unit.server_test_util import ServerTestUtil

# pylint: disable=import-outside-toplevel

PROPERTY = "_NET_WM_NAME"
PROPERTY_TYPE = "UTF8_STRING"
# the six properties that a window title update touches:
STORM_PROPERTIES = (
    "_NET_WM_NAME", "_NET_WM_ICON_NAME", "WM_NAME",
    "WM_LOCALE_NAME", "WM_ICON_NAME", "WM_CLIENT_MACHINE",
)

STORM_DURATION = 2       # seconds
# the storm thread updates all the `STORM_PROPERTIES` this many times per batch,
# and pauses this long between batches: (roughly 10 thousand events per second)
STORM_BATCH = 2
STORM_INTERVAL = 0.001
# the event handler sleeps this long for every event,
# to ensure that we process events slower than the storm generates them:
# (5 thousand events per second at most)
HANDLER_DELAY = 0.0002
# the longest we tolerate between two idle callbacks during the storm,
# and the longest we tolerate a timer being delayed:
MAX_IDLE_GAP = 1.0
MAX_TIMER_DELAY = 1.0


def storm_thread(display_name: str, xid: int, stop: Event) -> None:
    """
    Generate a property event storm from a separate X11 connection,
    (Xlib is not thread safe, so we can't re-use the one the bindings use)
    just like an application setting its window title on every frame does.
    """
    xlib = ctypes.CDLL("libX11.so.6")
    xlib.XOpenDisplay.restype = ctypes.c_void_p
    xlib.XOpenDisplay.argtypes = [ctypes.c_char_p]
    xlib.XCloseDisplay.argtypes = [ctypes.c_void_p]
    xlib.XInternAtom.restype = ctypes.c_ulong
    xlib.XInternAtom.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int]
    xlib.XChangeProperty.argtypes = [
        ctypes.c_void_p, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_ulong,
        ctypes.c_int, ctypes.c_int, ctypes.c_char_p, ctypes.c_int,
    ]
    xlib.XFlush.argtypes = [ctypes.c_void_p]
    display = xlib.XOpenDisplay(display_name.encode())
    assert display, f"failed to open display {display_name!r}"
    try:
        atoms = [xlib.XInternAtom(display, name.encode(), 0) for name in STORM_PROPERTIES]
        utf8 = xlib.XInternAtom(display, b"UTF8_STRING", 0)
        value = b"Xpra title property event storm"
        PropModeReplace = 0
        while not stop.is_set():
            for _ in range(STORM_BATCH):
                for atom in atoms:
                    xlib.XChangeProperty(display, xid, atom, utf8, 8, PropModeReplace, value, len(value))
            xlib.XFlush(display)
            sleep(STORM_INTERVAL)
    finally:
        xlib.XCloseDisplay(display)


def run_storm(display_name: str) -> int:
    """
    Runs in its own process: registers the X11 event source with the GLib main loop,
    then verifies that idle callbacks keep running whilst a window
    generates X11 events faster than we can process them.
    Returns 0 on success.
    """
    from xpra.os_util import gi_import
    from xpra.util.gobject import one_arg_signal
    GLib = gi_import("GLib")
    GObject = gi_import("GObject")

    from xpra.x11.bindings.core import constants, get_root_xid
    from xpra.x11.bindings.display_source import X11DisplayContext
    from xpra.x11.bindings.window import X11WindowBindings
    from xpra.x11.bindings.loop import register_glib_source
    from xpra.x11.dispatch import add_event_receiver, remove_event_receiver

    class SlowReceiver(GObject.GObject):
        __gsignals__ = {
            "x11-property-notify-event": one_arg_signal,
        }

        def __init__(self):
            super().__init__()
            self.count = 0

        def do_x11_property_notify_event(self, _event) -> None:
            self.count += 1
            # simulate the cost of handling the event,
            # (the real handlers make synchronous property requests),
            # this also releases the GIL so the storm thread can run:
            sleep(HANDLER_DELAY)

    idle_runs: list[float] = []
    stop = Event()

    def on_idle() -> bool:
        idle_runs.append(monotonic())
        # re-arm after a short pause,
        # (if we returned True, GLib would just call us again straight away)
        GLib.timeout_add(5, rearm_idle)
        return False

    def rearm_idle() -> bool:
        GLib.idle_add(on_idle)
        return False

    with X11DisplayContext(display_name):
        main_loop = GLib.MainLoop()
        register_glib_source(main_loop.get_context())
        x11window = X11WindowBindings()
        root = get_root_xid()
        window = x11window.CreateWindow(root, 0, 0, 32, 32)
        receiver = SlowReceiver()
        try:
            x11window.addXSelectInput(window, constants["PropertyChangeMask"])
            add_event_receiver(window, receiver)
            x11window.XSync()

            thread = Thread(target=storm_thread, args=(display_name, window, stop), daemon=True)

            def watchdog() -> None:
                # if the main loop is starved, the timers below cannot fire,
                # so the storm has to be stopped from here:
                sleep(STORM_DURATION + 1)
                stop.set()
                thread.join(10)
                sleep(10)
                # the main loop is still stuck 10s after the storm has ended
                print(f"main loop watchdog timeout, idle runs={len(idle_runs)}, events handled={receiver.count}")
                sys.stdout.flush()
                os._exit(2)

            Thread(target=watchdog, daemon=True).start()
            start = monotonic()
            GLib.idle_add(on_idle)
            GLib.timeout_add(100, thread.start)
            GLib.timeout_add(100 + STORM_DURATION * 1000, stop.set)
            # give the backlog some time to drain before quitting:
            quit_delay = 100 + STORM_DURATION * 1000 + 500
            GLib.timeout_add(quit_delay, main_loop.quit)
            main_loop.run()
            end = monotonic()
            stop.set()
            thread.join(10)
        finally:
            remove_event_receiver(window, receiver)
            x11window.DestroyWindow(window)
            x11window.XSync()

    # the gaps between idle runs, including the time before the first one and after the last one:
    times = [start] + idle_runs + [end]
    max_gap = max(b - a for a, b in pairwise(times))
    timer_delay = end - start - quit_delay / 1000
    print(f"{receiver.count} events handled in {end - start:.1f}s, {len(idle_runs)} idle runs,")
    print(f" longest gap between idle runs: {max_gap:.3f}s, quit timer delayed by {timer_delay:.3f}s")
    if receiver.count < 1000:
        print("the event storm did not materialize")
        return 1
    if max_gap > MAX_IDLE_GAP:
        print("the X11 event storm starved the main loop's idle callbacks")
        return 1
    if timer_delay > MAX_TIMER_DELAY:
        print("the X11 event storm starved the main loop's timers")
        return 1
    return 0


class X11EventLoopTest(ServerTestUtil):

    def test_process_events_budget(self):
        display = self.find_free_display()
        xvfb = self.start_Xvfb(display)
        try:
            with OSEnvContext():
                os.environ["DISPLAY"] = display
                from xpra.x11.bindings.core import constants, get_root_xid
                from xpra.x11.bindings.display_source import X11DisplayContext
                from xpra.x11.bindings.window import X11WindowBindings
                from xpra.x11.bindings import loop as loop_module

                with X11DisplayContext(display):
                    x11window = X11WindowBindings()
                    root = get_root_xid()
                    window = x11window.CreateWindow(root, 0, 0, 32, 32)
                    try:
                        x11window.addXSelectInput(window, constants["PropertyChangeMask"])
                        event_loop = loop_module.EventLoop()
                        # start from an empty queue:
                        x11window.XSync()
                        while event_loop.process_events():
                            pass

                        max_events = loop_module.MAX_EVENTS
                        self.assertGreater(max_events, 0)
                        n = max_events * 4
                        for i in range(n):
                            x11window.XChangeProperty(window, PROPERTY, PROPERTY_TYPE, 8, b"title %i" % i)
                        x11window.XSync()
                        # the first batch must not exceed the budget:
                        count = event_loop.process_events()
                        self.assertGreater(count, 0)
                        self.assertLessEqual(count, max_events)
                        # but subsequent calls must find the remaining events:
                        total = count
                        calls = 1
                        while count:
                            count = event_loop.process_events()
                            total += count
                            calls += 1
                            self.assertLessEqual(count, max_events)
                        self.assertEqual(total, n)
                        self.assertGreaterEqual(calls, 4)

                        # `0` disables the limits:
                        saved = loop_module.MAX_EVENTS, loop_module.MAX_EVENT_TIME
                        try:
                            loop_module.MAX_EVENTS = 0
                            loop_module.MAX_EVENT_TIME = 0
                            for i in range(n):
                                x11window.XChangeProperty(window, PROPERTY, PROPERTY_TYPE, 8, b"title %i" % i)
                            x11window.XSync()
                            self.assertEqual(event_loop.process_events(), n)
                            self.assertEqual(event_loop.process_events(), 0)
                        finally:
                            loop_module.MAX_EVENTS, loop_module.MAX_EVENT_TIME = saved
                    finally:
                        x11window.DestroyWindow(window)
        finally:
            xvfb.terminate()
            self.assertIsNotNone(pollwait(xvfb, 10))

    def test_event_storm_fairness(self):
        display = self.find_free_display()
        xvfb = self.start_Xvfb(display)
        try:
            # the GLib source can only be registered once per process,
            # so run this scenario in a separate process:
            import subprocess
            env = os.environ.copy()
            env["DISPLAY"] = display
            unittests_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            # inherit this process's search path, it already found both `unit` and `xpra`:
            env["PYTHONPATH"] = os.pathsep.join([unittests_dir] + [x for x in sys.path if x])
            cmd = [sys.executable, os.path.abspath(__file__), "storm", display]
            proc = subprocess.run(cmd, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=60, check=False)
            output = proc.stdout.decode(errors="replace")
            self.assertEqual(proc.returncode, 0, f"event storm test failed:\n{output}")
        finally:
            xvfb.terminate()
            self.assertIsNotNone(pollwait(xvfb, 10))


def main():
    if len(sys.argv) == 3 and sys.argv[1] == "storm":
        sys.exit(run_storm(sys.argv[2]))
    if POSIX and not OSX:
        unittest.main()


if __name__ == '__main__':
    main()
