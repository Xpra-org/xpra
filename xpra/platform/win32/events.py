#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2011 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from collections.abc import Callable
from ctypes import (
    sizeof, byref,
    WinError, get_last_error,  # @UnresolvedImport
)

from xpra.util.env import envbool
from xpra.platform.win32.wtsapi import (
    NOTIFY_FOR_THIS_SESSION,
    WM_WTSSESSION_CHANGE, WM_DWMNCRENDERINGCHANGED, WM_DWMCOMPOSITIONCHANGED,
    WTSRegisterSessionNotification, WTSUnRegisterSessionNotification,
)
from xpra.platform.win32.wndproc_events import WNDPROC_EVENT_NAMES
from xpra.platform.win32 import constants as win32con
from xpra.platform.win32.common import (
    WNDCLASSEX, WNDPROC,
    RegisterClassExW,
    CreateWindowExA, DestroyWindow,
    UnregisterClassW, DefWindowProcW,
    GetModuleHandleA,
    GetStockObject,
)
from xpra.log import Logger

log = Logger("events", "win32")

KNOWN_EVENTS = {}
POWER_EVENTS = {}
for x in dir(win32con):
    if x.endswith("_EVENT"):
        v = getattr(win32con, x)
        KNOWN_EVENTS[v] = x
    if x.startswith("PBT_"):
        v = getattr(win32con, x)
        POWER_EVENTS[v] = x

IGNORE_EVENTS = {
    win32con.WM_ACTIVATEAPP: "WM_ACTIVATEAPP",
    win32con.WM_TIMECHANGE: "WM_TIMECHANGE",
    win32con.WM_DESTROY: "WM_DESTROY",
    win32con.WM_COMMAND: "WM_COMMAND",
    win32con.WM_DEVICECHANGE: "WM_DEVICECHANGE",
    win32con.WM_DISPLAYCHANGE: "WM_DISPLAYCHANGE",  # already taken care of by gtk event
    win32con.WM_NCCALCSIZE: "WM_NCCALCSIZE",  # happens after resume too?
    win32con.WM_WINDOWPOSCHANGED: "WM_WINDOWPOSCHANGED",  # happens after resume too?
    win32con.WM_WININICHANGE: "WM_WININICHANGE",  # happens after resume too?
    win32con.WM_WINDOWPOSCHANGING: "WM_WINDOWPOSCHANGING",
    win32con.WM_GETMINMAXINFO: "WM_GETMINMAXINFO",
    win32con.WM_SYSCOLORCHANGE: "WM_SYSCOLORCHANGE",
    WM_WTSSESSION_CHANGE: "WM_WTSSESSION_CHANGE",
    WM_DWMNCRENDERINGCHANGED: "WM_DWMNCRENDERINGCHANGED",
    800: "screen background changed",  # I can't find this definition anywhere
    win32con.WM_SIZE: "WM_SIZE: screen resized",  # we get a GTK signal for this
}
LOG_EVENTS = {
    win32con.WM_POWERBROADCAST: "WM_POWERBROADCAST: power management event",
    win32con.WM_TIMECHANGE: "WM_TIMECHANGE: time change event",
    win32con.WM_INPUTLANGCHANGE: "WM_INPUTLANGCHANGE: input language changed",
    WM_DWMCOMPOSITIONCHANGED: "WM_DWMCOMPOSITIONCHANGED: Desktop Window Manager composition has been enabled or disabled",
}
KNOWN_WM_EVENTS = IGNORE_EVENTS.copy()
KNOWN_WM_EVENTS.update(WNDPROC_EVENT_NAMES)
NIN_BALLOONSHOW = win32con.WM_USER + 2
NIN_BALLOONHIDE = win32con.WM_USER + 3
NIN_BALLOONTIMEOUT = win32con.WM_USER + 4
NIN_BALLOONUSERCLICK = win32con.WM_USER + 5
BALLOON_EVENTS = {
    NIN_BALLOONSHOW: "NIN_BALLOONSHOW",
    NIN_BALLOONHIDE: "NIN_BALLOONHIDE",
    NIN_BALLOONTIMEOUT: "NIN_BALLOONTIMEOUT",
    NIN_BALLOONUSERCLICK: "NIN_BALLOONUSERCLICK",
}
KNOWN_WM_EVENTS.update(BALLOON_EVENTS)

# anything else we don't have yet:
for x in dir(win32con):
    if x.startswith("WM_") and x not in KNOWN_WM_EVENTS:
        v = getattr(win32con, x)
        KNOWN_WM_EVENTS[v] = x

WINDOW_EVENTS = envbool("XPRA_WIN32_WINDOW_EVENTS", True)

EVENT_CALLBACK_TYPE = Callable[[int, int], None]


def add_handler(event: str, handler: Callable) -> None:
    pass


def remove_handler(event: str, handler: Callable) -> None:
    pass


class Win32Eventlistener:

    def __init__(self):
        assert singleton is None
        self.hwnd = None
        self.event_callbacks: dict[int, list[EVENT_CALLBACK_TYPE]] = {}
        self.ignore_events = IGNORE_EVENTS
        self.log_events = LOG_EVENTS

        if not WINDOW_EVENTS:
            return

        self.wc = WNDCLASSEX()
        self.wc.cbSize = sizeof(WNDCLASSEX)
        self.wc.style = win32con.CS_GLOBALCLASS | win32con.CS_VREDRAW | win32con.CS_HREDRAW
        self.wc.lpfnWndProc = WNDPROC(self.WndProc)
        self.wc.cbClsExtra = 0
        self.wc.cbWndExtra = 0
        self.wc.hInstance = GetModuleHandleA(0)
        self.wc.hIcon = 0
        self.wc.hCursor = 0
        self.wc.hBrush = GetStockObject(win32con.WHITE_BRUSH)
        self.wc.lpszMenuName = 0
        self.wc.lpszClassName = "Xpra-Event-Window"
        self.wc.hIconSm = 0
        self.wc.hbrBackground = win32con.COLOR_WINDOW
        self.wc_atom = RegisterClassExW(byref(self.wc))
        if self.wc_atom == 0:
            raise WinError(get_last_error())

        self.hwnd = CreateWindowExA(0, self.wc_atom, "For xpra event listener only",
                                    win32con.WS_CAPTION,
                                    0, 0, win32con.CW_USEDEFAULT, win32con.CW_USEDEFAULT,
                                    0, 0, self.wc.hInstance, None)
        if self.hwnd == 0:
            raise WinError(get_last_error())

        # register our interest in session events:
        # http://timgolden.me.uk/python/win32_how_do_i/track-session-events.html#isenslogon
        # http://stackoverflow.com/questions/365058/detect-windows-logout-in-python
        # http://msdn.microsoft.com/en-us/library/aa383841.aspx
        # http://msdn.microsoft.com/en-us/library/aa383828.aspx
        WTSRegisterSessionNotification(self.hwnd, NOTIFY_FOR_THIS_SESSION)
        log("Win32Eventlistener created with hwnd=%s", self.hwnd)

    def cleanup(self):
        log("Win32Eventlistener.cleanup()")
        self.event_callbacks = {}

        hwnd = self.hwnd
        if hwnd:
            WTSUnRegisterSessionNotification(hwnd)

            self.hwnd = None
            try:
                DestroyWindow(hwnd)
            except Exception as e:
                log.error("Error during cleanup of event window instance:")
                log.estr(e)

            try:
                UnregisterClassW(self.wc.lpszClassName, self.wc.hInstance)
            except Exception as e:
                log.error("Error during cleanup of event window class:")
                log.estr(e)

    def add_event_callback(self, event: int, callback: EVENT_CALLBACK_TYPE):
        self.event_callbacks.setdefault(event, []).append(callback)

    def remove_event_callback(self, event: int, callback: EVENT_CALLBACK_TYPE):
        callbacks = self.event_callbacks.get(event, [])
        if callback in callbacks:
            callbacks.remove(callback)

    def WndProc(self, hWnd: int, msg: int, wParam: int, lParam: int):
        callbacks = self.event_callbacks.get(msg)
        event_name = KNOWN_WM_EVENTS.get(msg, hex(msg))
        log("callbacks for event %s: %s", event_name, callbacks)
        if hWnd == self.hwnd:
            if callbacks:
                for c in callbacks:
                    with log.trap_error("Error on event callback %s", c):
                        c(wParam, lParam)
            elif msg in self.ignore_events:
                log("%s: %s / %s", self.ignore_events.get(msg), wParam, lParam)
            elif msg in self.log_events:
                log.info("%s: %s / %s", self.log_events.get(msg), wParam, lParam)
            else:
                log_fn = log.warn
                if 0 <= msg <= win32con.WM_USER or msg > 0xFFFF:
                    ut = "reserved system"
                elif win32con.WM_USER <= msg <= 0x7FFF:
                    ut = "WM_USER"
                elif 0x8000 <= msg <= 0xBFFF:
                    ut = "WM_APP"
                elif 0xC000 <= msg <= 0xFFFF:
                    ut = "string"
                    log_fn = log.debug
                else:
                    ut = "/ unexpected"
                log_fn("unknown %s message: %s / %#x / %#x", ut, event_name, int(wParam), int(lParam))
            if msg == win32con.WM_DESTROY:
                self.cleanup()
        elif self.hwnd and hWnd:
            log.warn("invalid hwnd: %s (expected %s)", hWnd, self.hwnd)
        r = DefWindowProcW(hWnd, msg, wParam, lParam)
        log("DefWindowProc%s=%s", (hWnd, msg, wParam, lParam), r)
        return r


singleton: Win32Eventlistener | None = None


def get_win32_event_listener(create=True) -> Win32Eventlistener | None:
    global singleton
    if not singleton and create:
        singleton = Win32Eventlistener()
    return singleton
