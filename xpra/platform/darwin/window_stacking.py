# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import ctypes

import objc
from AppKit import (
    NSObject, NSWindow, NSNotificationCenter,
    NSWindowNumberListAllSpaces,
    NSWindowDidBecomeKeyNotification,
    NSWindowDidBecomeMainNotification,
    NSWindowDidChangeOcclusionStateNotification,
    NSWindowDidMiniaturizeNotification,
    NSWindowDidDeminiaturizeNotification,
    NSApplicationDidBecomeActiveNotification,
)

from xpra.util.env import envint, envbool
from xpra.os_util import gi_import
from xpra.log import Logger

log = Logger("osx", "focus")

GLib = gi_import("GLib")

# a single user action generates a burst of notifications:
# coalesce them before asking the window server for the whole order again
STACKING_DELAY = envint("XPRA_OSX_STACKING_DELAY", 50)
# without this, the windows which are on another space are missing from the order
# and the server would restack them as if they had been lowered:
ALL_SPACES = envbool("XPRA_OSX_STACKING_ALL_SPACES", True)
ORDER_NOTIFICATIONS = envbool("XPRA_OSX_STACKING_ORDER_NOTIFICATIONS", True)

# AppKit has no public notification for the z-order itself, unlike the
# `EVENT_OBJECT_REORDER` window event on MS Windows or the `_NET_CLIENT_LIST_STACKING`
# property on X11. What we can observe is:
# * the events which usually *accompany* a change of order - a window being activated,
#   miniaturized or occluded. These are public, but they say nothing about the order
#   itself: a window ordered without being activated does not post any of them.
# * our own ordering calls, which the `window` subsystem reports via `schedule_update`
NOTIFICATIONS = (
    NSWindowDidBecomeKeyNotification,
    NSWindowDidBecomeMainNotification,
    NSWindowDidChangeOcclusionStateNotification,
    NSWindowDidMiniaturizeNotification,
    NSWindowDidDeminiaturizeNotification,
    NSApplicationDidBecomeActiveNotification,
)
# ..and the notifications AppKit posts for the ordering itself, which cover the cases
# the ones above miss (a window raised or hidden without ever becoming key).
# These names are not declared in the AppKit headers and PyObjC does not export them,
# so they are used as plain strings: an observer registered for a name which is never
# posted simply never fires, which is why this needs no version check
ORDER_NOTIFICATION_NAMES = (
    "NSWindowDidOrderOnScreenAndFinishAnimatingNotification",
    "NSWindowDidOrderOffScreenNotification",
)


def get_notification_names() -> tuple[str, ...]:
    names = tuple(str(notification) for notification in NOTIFICATIONS)
    if ORDER_NOTIFICATIONS:
        names += ORDER_NOTIFICATION_NAMES
    return names


def get_nswindow(window):
    """
    The `NSWindow` backing a client window, or `None`.
    `get_window_handle` returns the `NSView` pointer on macOS.
    """
    handle = window.get_window_handle()
    if not handle:
        return None
    nsview = objc.objc_object(c_void_p=ctypes.c_void_p(handle))
    return nsview.window()


def get_window_numbers() -> tuple[int, ...]:
    """
    Our application's on-screen windows, from the topmost one down.
    This is the macOS equivalent of walking the desktop z-order with `EnumWindows`,
    except that it is already restricted to our own process,
    and that the windows which have been ordered out are left out for us.
    """
    options = NSWindowNumberListAllSpaces if ALL_SPACES else 0
    return tuple(int(number) for number in NSWindow.windowNumbersWithOptions_(options))


class StackingObserver(NSObject):
    """
    Forwards the AppKit notifications which may accompany a z-order change.
    Observing with no object at all covers the windows created later, too.
    """

    # noinspection PyTypeHints
    def initWithCallback_(self, callback):
        objc_self = objc.super(StackingObserver, self).init()
        if objc_self is None:
            return None
        objc_self.callback = callback
        return objc_self

    def orderMayHaveChanged_(self, notification) -> None:
        log("orderMayHaveChanged_(%s)", notification.name())
        self.callback()


class DarwinWindowStackingWatcher:
    """
    Watches the application's window z-order and feeds the bottom-to-top
    window order to the `window` subsystem.

    This is an OS concern rather than a toolkit one: all it needs is the native
    window handle that every client window backend exposes via `get_window_handle`.
    """

    def __init__(self, window_client):
        self.window = window_client
        self.observer = None
        self.stacking_timer = 0

    def setup(self) -> None:
        # whether the server wants a stacking order is only known after the handshake:
        self.window.client.after_handshake(self.do_setup)

    def do_setup(self, *args) -> None:
        log("do_setup%s server_window_stacking=%s", args, self.window.server_window_stacking)
        if not self.window.server_window_stacking or self.observer:
            return
        self.observer = StackingObserver.alloc().initWithCallback_(self.schedule_update)
        center = NSNotificationCenter.defaultCenter()
        names = get_notification_names()
        for name in names:
            center.addObserver_selector_name_object_(self.observer, b"orderMayHaveChanged:", name, None)
        log("added observer %s for %s", self.observer, names)
        # ensure the server gets the initial order:
        self.update_stacking()

    def cleanup(self) -> None:
        log("cleanup() observer=%s", self.observer)
        self.cancel_stacking_timer()
        if observer := self.observer:
            self.observer = None
            NSNotificationCenter.defaultCenter().removeObserver_(observer)

    def schedule_update(self) -> None:
        # these notifications fire for every window activated, miniaturized or occluded:
        # `update_stacking` works out whether anything has actually moved
        if not self.stacking_timer:
            self.stacking_timer = GLib.timeout_add(STACKING_DELAY, self.stacking_timeout)

    def cancel_stacking_timer(self) -> None:
        if st := self.stacking_timer:
            self.stacking_timer = 0
            GLib.source_remove(st)

    def stacking_timeout(self) -> bool:
        self.stacking_timer = 0
        self.update_stacking()
        return False

    def update_stacking(self) -> None:
        # `send_window_stacking` only emits a packet if the order has changed:
        self.window.send_window_stacking(self.get_window_stacking(self.window))

    @staticmethod
    def get_window_stacking(window_client) -> tuple[int, ...]:
        number_to_wid: dict[int, int] = {}
        for wid, window in window_client._id_to_window.items():
            if window.is_tray():
                # a system tray icon is an `NSStatusItem`, not a window of its own
                continue
            nswindow = get_nswindow(window)
            if nswindow:
                number_to_wid[nswindow.windowNumber()] = wid
        # `windowNumbersWithOptions:` returns the topmost window first,
        # the xpra server expects the reverse:
        numbers = get_window_numbers()
        stacking = tuple(number_to_wid[number] for number in reversed(numbers) if number in number_to_wid)
        log("window numbers=%s, window stacking=%s", numbers, stacking)
        return stacking
