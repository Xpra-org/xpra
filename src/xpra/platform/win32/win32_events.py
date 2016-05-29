#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2011-2014 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import win32ts          #@UnresolvedImport
import win32con         #@UnresolvedImport
import win32api         #@UnresolvedImport
import win32gui         #@UnresolvedImport

from xpra.log import Logger
log = Logger("events", "win32")

from xpra.platform.win32.wndproc_events import WNDPROC_EVENT_NAMES

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


class Win32EventListener(object):

    def __init__(self):
        assert singleton is None
        self.wc = win32gui.WNDCLASS()
        self.wc.lpszClassName = 'XpraEventWindow'
        self.wc.style =  win32con.CS_GLOBALCLASS|win32con.CS_VREDRAW|win32con.CS_HREDRAW
        self.wc.hbrBackground = win32con.COLOR_WINDOW
        #shame we would have to register those in advance:
        self.wc.lpfnWndProc = {}    #win32con.WM_SOMETHING : OnSomething}
        win32gui.RegisterClass(self.wc)
        self.hwnd = win32gui.CreateWindow(self.wc.lpszClassName,
                        'For events only',
                        win32con.WS_CAPTION,
                        100, 100, 900, 900, 0, 0, 0, None)
        self.old_win32_proc = None
        self.event_callbacks = {}
        self.ignore_events = IGNORE_EVENTS
        self.log_events = LOG_EVENTS
        self.detect_win32_session_events()
        log("Win32EventListener create with hwnd=%s", self.hwnd)

    def add_event_callback(self, event, callback):
        self.event_callbacks.setdefault(event, []).append(callback)

    def remove_event_callback(self, event, callback):
        l = self.event_callbacks.get(event)
        if l and callback in l:
            l.remove(callback)

    def cleanup(self):
        log("Win32EventListener.cleanup()")
        self.event_callback = {}
        self.stop_win32_session_events()
        if self.hwnd:
            try:
                win32gui.DestroyWindow(self.hwnd)
            except Exception as e:
                log.error("Error during cleanup of event window instance:")
                log.error(" %s", e)
            self.hwnd = None
            try:
                win32gui.UnregisterClass(self.wc.lpszClassName, None)
            except Exception as e:
                log.error("Error during cleanup of event window class:")
                log.error(" %s", e)

    def stop_win32_session_events(self):
        log("stop_win32_session_events() old win32 proc=%s", self.old_win32_proc)
        if not self.old_win32_proc:
            return
        try:
            if self.hwnd:
                win32api.SetWindowLong(self.hwnd, win32con.GWL_WNDPROC, self.old_win32_proc)
                self.old_win32_proc = None
                win32ts.WTSUnRegisterSessionNotification(self.hwnd)
            else:
                log.warn("stop_win32_session_events() missing handle!")
        except:
            log.error("stop_win32_session_events", exc_info=True)

    def detect_win32_session_events(self):
        """
        Use pywin32 to receive session notification events.
        """
        if self.hwnd is None:
            log.warn("detect_win32_session_events() missing handle!")
            return
        try:
            log("detect_win32_session_events() hwnd=%s", self.hwnd)
            #register our interest in those events:
            #http://timgolden.me.uk/python/win32_how_do_i/track-session-events.html#isenslogon
            #http://stackoverflow.com/questions/365058/detect-windows-logout-in-python
            #http://msdn.microsoft.com/en-us/library/aa383841.aspx
            #http://msdn.microsoft.com/en-us/library/aa383828.aspx
            win32ts.WTSRegisterSessionNotification(self.hwnd, win32ts.NOTIFY_FOR_THIS_SESSION)
            #catch all events: http://wiki.wxpython.org/HookingTheWndProc
            self.old_win32_proc = win32gui.SetWindowLong(self.hwnd, win32con.GWL_WNDPROC, self.MyWndProc)
        except Exception as e:
            log.error("failed to hook session notifications: %s", e)

    def MyWndProc(self, hWnd, msg, wParam, lParam):
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
                l("unknown %s message: %s / %s / %s", ut, event_name, wParam, lParam)
        else:
            log.warn("invalid hwnd: %s (expected %s)", hWnd, self.hwnd)
        # Pass all messages to the original WndProc
        try:
            return win32gui.CallWindowProc(self.old_win32_proc, hWnd, msg, wParam, lParam)
        except Exception as e:
            log.error("error delegating call for %s: %s", event_name, e)
