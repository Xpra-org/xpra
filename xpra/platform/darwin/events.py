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
    NSNotificationCenter,
    NSMenuDidBeginTrackingNotification,
    NSMenuDidEndTrackingNotification,
)

from xpra.os_util import gi_import
from xpra.util.env import envbool, envint
from xpra.log import Logger

GLib = gi_import("GLib")

log = Logger("osx", "events")
workspacelog = Logger("osx", "events", "workspace")
menulog = Logger("osx", "events", "menu")

SLEEP_HANDLER = envbool("XPRA_OSX_SLEEP_HANDLER", True)
MENU_TRACKING = envbool("XPRA_OSX_MENU_TRACKING", True)
# how long to wait before firing `unpause` when a menu closes:
MENU_TRACKING_DELAY = envint("XPRA_OSX_MENU_TRACKING_DELAY", 250)


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
        # number of menus currently tracking (submenus are nested),
        # whether we have fired the `pause` event for them,
        # and the timer used to delay the matching `unpause`:
        objc_self.menu_tracking: int = 0
        objc_self.menu_paused: bool = False
        objc_self.menu_untrack_timer: int = 0
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

    @objc.python_method
    def register_menu_tracking_handlers(self) -> None:
        menulog("register_menu_tracking_handlers()")
        # these notifications are posted by any `NSMenu` of this process:
        # the application menu bar, the tray menu, context menus and their submenus
        center = NSNotificationCenter.defaultCenter()

        def add_observer(fn: Callable, val) -> None:
            center.addObserver_selector_name_object_(self, fn, val, None)

        add_observer(self.receiveMenuBeginTrackingNotification_, NSMenuDidBeginTrackingNotification)
        add_observer(self.receiveMenuEndTrackingNotification_, NSMenuDidEndTrackingNotification)

    @objc.typedSelector(b'v@:I')
    def receiveMenuBeginTrackingNotification_(self, notification) -> None:
        # whilst a menu is open, `AppKit` runs a nested event loop
        # which does not service the main loop at all:
        # tell the server to slow down before we get starved,
        # rather than waiting for the UI thread watcher to figure it out
        self.cancel_menu_untrack_timer()
        self.menu_tracking += 1
        menulog("receiveMenuBeginTrackingNotification_(%s) menu_tracking=%i", notification, self.menu_tracking)
        if not self.menu_paused:
            self.menu_paused = True
            self.call_handlers("pause")

    @objc.typedSelector(b'v@:I')
    def receiveMenuEndTrackingNotification_(self, notification) -> None:
        self.menu_tracking = max(0, self.menu_tracking - 1)
        menulog("receiveMenuEndTrackingNotification_(%s) menu_tracking=%i", notification, self.menu_tracking)
        if self.menu_tracking or self.menu_untrack_timer:
            return
        # don't resume immediately: moving from one menu to the next in the menu bar
        # ends the first menu's tracking just before the next one begins,
        # and we don't want to trigger a full refresh in between.
        # (this timer can only fire once the main loop is being serviced again)
        self.menu_untrack_timer = GLib.timeout_add(MENU_TRACKING_DELAY, self.menu_untrack)

    @objc.python_method
    def menu_untrack(self) -> bool:
        self.menu_untrack_timer = 0
        menulog("menu_untrack() menu_tracking=%i, menu_paused=%s", self.menu_tracking, self.menu_paused)
        if not self.menu_tracking and self.menu_paused:
            self.menu_paused = False
            self.call_handlers("unpause")
        return False

    @objc.python_method
    def cancel_menu_untrack_timer(self) -> None:
        if mut := self.menu_untrack_timer:
            self.menu_untrack_timer = 0
            GLib.source_remove(mut)

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
        if MENU_TRACKING:
            delegate.register_menu_tracking_handlers()
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
