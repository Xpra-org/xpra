#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2011 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os

from collections.abc import Callable

import objc
from Quartz import (
    CGWindowListCopyWindowInfo, kCGWindowListOptionOnScreenOnly,
    kCGNullWindowID, kCGWindowListOptionAll,
)
from AppKit import (
    NSObject, NSWorkspace, NSApplication,
    NSWorkspaceActiveSpaceDidChangeNotification,
    NSWorkspaceWillSleepNotification,
    NSWorkspaceDidWakeNotification,
)

from xpra.util.env import envbool
from xpra.log import Logger

log = Logger("osx", "events")
workspacelog = Logger("osx", "events", "workspace")

SLEEP_HANDLER = envbool("XPRA_OSX_SLEEP_HANDLER", True)


class AppDelegate(NSObject):

    # noinspection PyTypeHints
    def init(self) -> None:
        objc_self = objc.super(AppDelegate, self).init()
        if self is None:
            return None
        objc_self.callbacks: dict[str, list[Callable]] = {}
        objc_self.workspace = None
        objc_self.notificationCenter = None
        return objc_self

    @objc.python_method
    def register_sleep_handlers(self):
        log("register_sleep_handlers()")
        self.workspace: NSWorkspace = NSWorkspace.sharedWorkspace()
        self.notificationCenter = self.workspace.notificationCenter()

        def add_observer(fn: Callable, val) -> None:
            self.notificationCenter.addObserver_selector_name_object_(self, fn, val, None)

        # NSWorkspaceWillPowerOffNotification
        add_observer(self.receiveSleepNotification_, NSWorkspaceWillSleepNotification)
        add_observer(self.receiveWakeNotification_, NSWorkspaceDidWakeNotification)
        add_observer(self.receiveWorkspaceChangeNotification_, NSWorkspaceActiveSpaceDidChangeNotification)

    @objc.typedSelector(b'B@:#B')
    def applicationShouldHandleReopen_hasVisibleWindows_(self, ns_app, flag):
        log("applicationShouldHandleReopen_hasVisibleWindows%s", (ns_app, flag))
        self.delegate_cb("deiconify")
        return True

    @objc.typedSelector(b'v@:I')
    def receiveWorkspaceChangeNotification_(self, aNotification):
        workspacelog("receiveWorkspaceChangeNotification_(%s)", aNotification)
        if not CGWindowListCopyWindowInfo:
            return
        with workspacelog.trap_error("Error querying workspace info"):
            ourpid = os.getpid()
            # list all windows on screen:
            option = kCGWindowListOptionAll | kCGWindowListOptionOnScreenOnly
            windowList = CGWindowListCopyWindowInfo(option, kCGNullWindowID)
            our_windows = {}
            for window in windowList:
                pid = window['kCGWindowOwnerPID']
                if pid == ourpid:
                    num = window['kCGWindowNumber']
                    name = window['kCGWindowName']
                    our_windows[num] = name
            workspacelog("workspace change - our windows on screen: %s", our_windows)
            if our_windows:
                self.call_handlers("resume")
            else:
                self.call_handlers("suspend")

    @objc.typedSelector(b'v@:I')
    def receiveSleepNotification_(self, notification):
        log("receiveSleepNotification_(%s)", notification)
        self.call_handlers("suspend")

    @objc.typedSelector(b'v@:I')
    def receiveWakeNotification_(self, notification):
        log("receiveWakeNotification_(%s)", notification)
        self.call_handlers("resume")

    @objc.python_method
    def call_handlers(self, name: str) -> None:
        callbacks = self.callbacks.get(name, [])
        log("delegate_cb(%s) callbacks=%s", name, callbacks)
        for callback in callbacks:
            with log.trap_error("Error in %s callback %s", name, callback):
                callback()

    def add_handler(self, event: str, handler: Callable) -> None:
        self.callbacks.setdefault(event, []).append(handler)

    def remove_handler(self, event: str, handler: Callable) -> None:
        callbacks = self.callbacks.get(event, [])
        if handler in callbacks:
            callbacks.remove(handler)


delegate = None
shared_app = None


def get_app_delegate() -> AppDelegate:
    global delegate, shared_app
    if not delegate:
        shared_app = NSApplication.sharedApplication()
        delegate = AppDelegate.alloc()
        delegate.init()
        delegate.retain()
        if SLEEP_HANDLER:
            delegate.register_sleep_handlers()
        shared_app.setDelegate_(delegate)
        log(f"setup_event_listener() the application delegate {delegate} has been registered with {shared_app}")
    return delegate


def add_handler(event: str, handler: Callable) -> None:
    get_app_delegate().add_handler(event, handler)


def remove_handler(event: str, handler: Callable) -> None:
    get_app_delegate().remove_handler(event, handler)
