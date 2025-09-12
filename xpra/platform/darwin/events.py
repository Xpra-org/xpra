#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2011 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import struct

from collections.abc import Callable

import objc
from Quartz import (
    CGWindowListCopyWindowInfo, kCGWindowListOptionOnScreenOnly,
    kCGNullWindowID, kCGWindowListOptionAll,
)
from AppKit import (
    NSObject, NSWorkspace, NSApplication,
    NSWorkspaceActiveSpaceDidChangeNotification,
    NSWorkspaceWillPowerOffNotification,
    NSWorkspaceWillSleepNotification,
    NSWorkspaceDidWakeNotification,
    NSAppleEventManager,
)

from xpra.util.env import envbool
from xpra.log import Logger

log = Logger("osx", "events")
workspacelog = Logger("osx", "events", "workspace")

SLEEP_HANDLER = envbool("XPRA_OSX_SLEEP_HANDLER", True)


def four_char_to_int(code: bytes) -> int:
    return struct.unpack(b'>l', code)[0]


GURL = four_char_to_int(b'GURL')


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
    def register_file_handler(self) -> None:
        log("register_file_handler()")
        try:
            from xpra.platform.darwin import get_OSXApplication
            get_OSXApplication().connect("NSApplicationOpenFile", self.open_file)
        except Exception as e:
            log.error("Error: cannot handle file associations:")
            log.estr(e)

    @objc.python_method
    def open_file(self, filename: str, *args) -> None:
        log("open_file(%s, %s)", filename, args)
        self.call_handlers("open-file", filename)

    @objc.python_method
    def set_file_handler(self, handler: Callable[[str], None]) -> None:
        log("set_file_handler(%s)", handler)
        self.add_handler("open-file", handler)

    @objc.python_method
    def register_url_handler(self) -> None:
        log("register_url_handler()")
        manager = NSAppleEventManager.sharedAppleEventManager()
        manager.setEventHandler_andSelector_forEventClass_andEventID_(
            self, "handleEvent:withReplyEvent:", GURL, GURL
        )

    @objc.python_method
    def set_url_handler(self, handler: Callable[[str], None]) -> None:
        log("set_url_handler(%s)", handler)
        self.add_handler("open-url", handler)

    def handleEvent_withReplyEvent_(self, event, reply_event) -> None:
        log("handleEvent_withReplyEvent_(%s, %s)", event, reply_event)
        url = event.descriptorForKeyword_(four_char_to_int(b'----')).stringValue()
        log("URL=%s", url)
        self.call_handlers("open-url", url)

    @objc.python_method
    def register_sleep_handlers(self) -> None:
        log("register_sleep_handlers()")
        self.workspace: NSWorkspace = NSWorkspace.sharedWorkspace()
        self.notificationCenter = self.workspace.notificationCenter()

        def add_observer(fn: Callable, val) -> None:
            self.notificationCenter.addObserver_selector_name_object_(self, fn, val, None)

        add_observer(self.receivePowerOffNotification_, NSWorkspaceWillPowerOffNotification)
        add_observer(self.receiveSleepNotification_, NSWorkspaceWillSleepNotification)
        add_observer(self.receiveWakeNotification_, NSWorkspaceDidWakeNotification)
        add_observer(self.receiveWorkspaceChangeNotification_, NSWorkspaceActiveSpaceDidChangeNotification)

    @objc.typedSelector(b'B@:#B')
    def applicationShouldHandleReopen_hasVisibleWindows_(self, ns_app, flag) -> bool:
        log("applicationShouldHandleReopen_hasVisibleWindows%s", (ns_app, flag))
        self.call_handlers("deiconify")
        return True

    @objc.typedSelector(b'v@:I')
    def receiveWorkspaceChangeNotification_(self, aNotification) -> None:
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
    def receivePowerOffNotification_(self, notification) -> None:
        log("receivePowerOffNotification_(%s)", notification)
        self.call_handlers("suspend")

    @objc.typedSelector(b'v@:I')
    def receiveSleepNotification_(self, notification) -> None:
        log("receiveSleepNotification_(%s)", notification)
        self.call_handlers("suspend")

    @objc.typedSelector(b'v@:I')
    def receiveWakeNotification_(self, notification) -> None:
        log("receiveWakeNotification_(%s)", notification)
        self.call_handlers("resume")

    @objc.python_method
    def call_handlers(self, name: str, *args) -> None:
        callbacks = self.callbacks.get(name, [])
        log("call_handlers(%s) callbacks=%s", name, callbacks)
        for callback in callbacks:
            with log.trap_error("Error in %s callback %s", name, callback):
                log("%s%s", callback, args)
                callback(*args)

    @objc.python_method
    def add_handler(self, event: str, handler: Callable) -> None:
        self.callbacks.setdefault(event, []).append(handler)

    @objc.python_method
    def remove_handler(self, event: str, handler: Callable) -> None:
        callbacks = self.callbacks.get(event, [])
        if handler in callbacks:
            callbacks.remove(handler)


delegate = None
shared_app = None


def get_app_delegate(create=True) -> AppDelegate:
    global delegate, shared_app
    if not delegate and create:
        shared_app = NSApplication.sharedApplication()
        delegate = AppDelegate.alloc()
        delegate.init()
        delegate.retain()
        if SLEEP_HANDLER:
            delegate.register_sleep_handlers()
        delegate.register_file_handler()
        delegate.register_url_handler()
        log("registered!")
        shared_app.setDelegate_(delegate)
        log(f"get_app_delegate() the application delegate {delegate} has been registered with {shared_app}")
    return delegate


def add_handler(event: str, handler: Callable) -> None:
    get_app_delegate().add_handler(event, handler)


def remove_handler(event: str, handler: Callable) -> None:
    get_app_delegate().remove_handler(event, handler)
