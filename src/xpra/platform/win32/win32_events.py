#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2011-2017 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import ctypes

from xpra.util import envbool
from xpra.log import Logger
log = Logger("events", "win32")

from xpra.platform.win32.wndproc_events import WNDPROC_EVENT_NAMES
from xpra.platform.win32 import constants as win32con
from xpra.platform.win32.common import (WNDCLASSEX, WNDPROC,
                                        RegisterClassExW,
                                        CreateWindowExA, DestroyWindow,
                                        UnregisterClassW, DefWindowProcW,
                                        GetModuleHandleA,
                                        GetStockObject)

try:
    wtsapi32 = ctypes.WinDLL("WtsApi32")
except Exception as e:
    log.error("Error: cannot load WtsApi2 DLL, session events will not be detected")
    log.error(" %s", e)
    del e
    wtsapi32 = None
NOTIFY_FOR_THIS_SESSION = 0

#no idea where we're supposed to get those from:
WM_WTSSESSION_CHANGE        = 0x02b1
WM_DWMNCRENDERINGCHANGED    = 0x031F
WM_DWMCOMPOSITIONCHANGED    = 0x031E
IGNORE_EVENTS = {
            win32con.WM_TIMECHANGE          : "WM_TIMECHANGE",
            win32con.WM_DESTROY             : "WM_DESTROY",
            win32con.WM_COMMAND             : "WM_COMMAND",
            win32con.WM_DEVICECHANGE        : "WM_DEVICECHANGE",
            win32con.WM_DISPLAYCHANGE       : "WM_DISPLAYCHANGE",       #already taken care of by gtk event
            win32con.WM_NCCALCSIZE          : "WM_NCCALCSIZE",          #happens after resume too?
            win32con.WM_WINDOWPOSCHANGED    : "WM_WINDOWPOSCHANGED",    #happens after resume too?
            win32con.WM_WININICHANGE        : "WM_WININICHANGE",        #happens after resume too?
            win32con.WM_WINDOWPOSCHANGING   : "WM_WINDOWPOSCHANGING",
            win32con.WM_GETMINMAXINFO       : "WM_GETMINMAXINFO",
            win32con.WM_SYSCOLORCHANGE      : "WM_SYSCOLORCHANGE",
            WM_WTSSESSION_CHANGE            : "WM_WTSSESSION_CHANGE",
            WM_DWMNCRENDERINGCHANGED        : "WM_DWMNCRENDERINGCHANGED",
            800                             : "screen background changed",  #I can't find this definition anywhere
            }
LOG_EVENTS = {
            win32con.WM_POWERBROADCAST      : "WM_POWERBROADCAST: power management event",
            win32con.WM_TIMECHANGE          : "WM_TIMECHANGE: time change event",
            win32con.WM_INPUTLANGCHANGE     : "WM_INPUTLANGCHANGE: input language changed",
            WM_DWMCOMPOSITIONCHANGED        : "WM_DWMCOMPOSITIONCHANGED: Desktop Window Manager composition has been enabled or disabled",
            }
KNOWN_WM_EVENTS = IGNORE_EVENTS.copy()
KNOWN_WM_EVENTS.update(WNDPROC_EVENT_NAMES)
NIN_BALLOONSHOW         = win32con.WM_USER + 2
NIN_BALLOONHIDE         = win32con.WM_USER + 3
NIN_BALLOONTIMEOUT      = win32con.WM_USER + 4
NIN_BALLOONUSERCLICK    = win32con.WM_USER + 5
BALLOON_EVENTS = {
            NIN_BALLOONSHOW             : "NIN_BALLOONSHOW",
            NIN_BALLOONHIDE             : "NIN_BALLOONHIDE",
            NIN_BALLOONTIMEOUT          : "NIN_BALLOONTIMEOUT",
            NIN_BALLOONUSERCLICK        : "NIN_BALLOONUSERCLICK",
          }
KNOWN_WM_EVENTS.update(BALLOON_EVENTS)

#anything else we don't have yet:
for x in dir(win32con):
    if x.startswith("WM_") and x not in KNOWN_WM_EVENTS:
        v = getattr(win32con, x)
        KNOWN_WM_EVENTS[v] = x


singleton = None
def get_win32_event_listener(create=True):
    global singleton
    if not singleton and create:
        singleton = Win32EventListener()
    return singleton

WINDOW_EVENTS = envbool("XPRA_WIN32_WINDOW_EVENTS", True)


class Win32EventListener(object):

    def __init__(self):
        assert singleton is None
        self.hwnd = None
        self.event_callbacks = {}
        self.ignore_events = IGNORE_EVENTS
        self.log_events = LOG_EVENTS

        if not WINDOW_EVENTS:
            return

        self.wc = WNDCLASSEX()
        self.wc.cbSize = ctypes.sizeof(WNDCLASSEX)
        self.wc.style =  win32con.CS_GLOBALCLASS|win32con.CS_VREDRAW|win32con.CS_HREDRAW
        self.wc.lpfnWndProc = WNDPROC(self.WndProc)
        self.wc.cbClsExtra = 0
        self.wc.cbWndExtra = 0
        self.wc.hInstance = GetModuleHandleA(0)
        self.wc.hIcon = 0
        self.wc.hCursor = 0
        self.wc.hBrush = GetStockObject(win32con.WHITE_BRUSH)
        self.wc.lpszMenuName = 0
        self.wc.lpszClassName = u'Xpra-Event-Window'
        self.wc.hIconSm = 0
        self.wc.hbrBackground = win32con.COLOR_WINDOW
        self.wc_atom = RegisterClassExW(ctypes.byref(self.wc))
        if self.wc_atom==0:
            raise ctypes.WinError(ctypes.get_last_error())

        self.hwnd = CreateWindowExA(0, self.wc_atom, u"For xpra event listener only",
            win32con.WS_CAPTION,
            0, 0, win32con.CW_USEDEFAULT, win32con.CW_USEDEFAULT,
            0, 0, self.wc.hInstance, None)
        if self.hwnd==0:
            raise ctypes.WinError(ctypes.get_last_error())

        if wtsapi32:
            #register our interest in session events:
            #http://timgolden.me.uk/python/win32_how_do_i/track-session-events.html#isenslogon
            #http://stackoverflow.com/questions/365058/detect-windows-logout-in-python
            #http://msdn.microsoft.com/en-us/library/aa383841.aspx
            #http://msdn.microsoft.com/en-us/library/aa383828.aspx
            wtsapi32.WTSRegisterSessionNotification(self.hwnd, NOTIFY_FOR_THIS_SESSION)
        log("Win32EventListener created with hwnd=%s", self.hwnd)


    def cleanup(self):
        log("Win32EventListener.cleanup()")
        self.event_callback = {}

        hwnd = self.hwnd
        if hwnd:
            if wtsapi32:
                wtsapi32.WTSUnRegisterSessionNotification(hwnd)

            self.hwnd = None
            try:
                DestroyWindow(hwnd)
            except Exception as e:
                log.error("Error during cleanup of event window instance:")
                log.error(" %s", e)

            wc = self.wc
            self.wc = None
            try:
                UnregisterClassW(wc.lpszClassName, wc.hInstance)
            except Exception as e:
                log.error("Error during cleanup of event window class:")
                log.error(" %s", e)


    def add_event_callback(self, event, callback):
        self.event_callbacks.setdefault(event, []).append(callback)

    def remove_event_callback(self, event, callback):
        l = self.event_callbacks.get(event)
        if l and callback in l:
            l.remove(callback)


    def WndProc(self, hWnd, msg, wParam, lParam):
        callbacks = self.event_callbacks.get(msg)
        event_name = KNOWN_WM_EVENTS.get(msg, hex(msg))
        log("callbacks for event %s: %s", event_name, callbacks)
        if hWnd==self.hwnd:
            if callbacks:
                for c in callbacks:
                    try:
                        c(wParam, lParam)
                    except:
                        log.error("error in callback %s", c, exc_info=True)
            elif msg in self.ignore_events:
                log("%s: %s / %s", self.ignore_events.get(msg), wParam, lParam)
            elif msg in self.log_events:
                log.info("%s: %s / %s", self.log_events.get(msg), wParam, lParam)
            else:
                l = log.warn
                if (msg>=0 and msg<=win32con.WM_USER) or msg>0xFFFF:
                    ut = "reserved system"
                elif msg>=win32con.WM_USER and msg<=0x7FFF:
                    ut = "WM_USER"
                elif msg>=0x8000 and msg<=0xBFFF:
                    ut = "WM_APP"
                elif msg>=0xC000 and msg<=0xFFFF:
                    ut = "string"
                    l = log.info
                else:
                    ut = "/ unexpected"
                l("unknown %s message: %s / %#x / %#x", ut, event_name, int(wParam), int(lParam))
        elif self.hwnd and hWnd!=None:
            log.warn("invalid hwnd: %s (expected %s)", hWnd, self.hwnd)
        if msg==win32con.WM_DESTROY:
            self.cleanup()
        r = DefWindowProcW(hWnd, msg, wParam, lParam)
        log("DefWindowProc%s=%s", (hWnd, msg, wParam, lParam), r)
        return r
