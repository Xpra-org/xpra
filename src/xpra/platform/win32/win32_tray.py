#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2011-2013 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

# Augments the win32_NotifyIcon "system tray" support class
# with methods for integrating with win32_balloon and the popup menu

import win32ts, win32con, win32api, win32gui        #@UnresolvedImport

from xpra.platform.win32.win32_NotifyIcon import win32NotifyIcon, WM_TRAY_EVENT, BUTTON_MAP
from xpra.client.tray_base import TrayBase, log, debug

#had to look this up online:
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
WM_WTSSESSION_CHANGE    = 0x02b1
IGNORE_EVENTS = {
            win32con.WM_DESTROY         : "WM_DESTROY",
            win32con.WM_COMMAND         : "WM_COMMAND",
            win32con.WM_DEVICECHANGE    : "WM_DEVICECHANGE",
            WM_WTSSESSION_CHANGE        : "WM_WTSSESSION_CHANGE",
            }
KNOWN_WM_EVENTS = {}
for x in dir(win32con):
    if x.startswith("WM_"):
        v = getattr(win32con, x)
        KNOWN_WM_EVENTS[v] = x


class Win32Tray(TrayBase):

    def __init__(self, *args):
        TrayBase.__init__(self, *args)
        self.default_icon_extension = "ico"
        self.default_icon_name = "xpra.ico"
        icon_filename = self.get_tray_icon_filename(self.default_icon_filename)
        self.tray_widget = win32NotifyIcon(self.tooltip, self.click_cb, self.exit_cb, None, icon_filename)
        #now let's try to hook the session notification
        self.detect_win32_session_events(self.getHWND())

    def ready(self):
        pass

    def show(self):
        pass

    def hide(self):
        pass


    def getHWND(self):
        if self.tray_widget is None:
            return    None
        return    self.tray_widget.hwnd

    def cleanup(self):
        debug("Win32Tray.cleanup() tray_widget=%s", self.tray_widget)
        if self.tray_widget:
            self.stop_win32_session_events(self.getHWND())
            self.tray_widget.close()
            self.tray_widget = None
        debug("Win32Tray.cleanup() ended")

    def set_tooltip(self, name):
        if self.tray_widget:
            self.tray_widget.set_tooltip(name)


    def set_icon_from_data(self, pixels, has_alpha, w, h, rowstride):
        if self.tray_widget:
            self.tray_widget.set_icon_from_data(pixels, has_alpha, w, h, rowstride)

    def do_set_icon_from_file(self, filename):
        if self.tray_widget:
            self.tray_widget.set_icon(filename)

    def set_blinking(self, on):
        if self.tray_widget:
            self.tray_widget.set_blinking(on)

    def get_geometry(self):
        return self.geometry_guess


    def stop_win32_session_events(self, app_hwnd):
        try:
            if self.old_win32_proc and app_hwnd:
                win32api.SetWindowLong(app_hwnd, win32con.GWL_WNDPROC, self.old_win32_proc)
                self.old_win32_proc = None

            if app_hwnd:
                win32ts.WTSUnRegisterSessionNotification(app_hwnd)
            else:
                log.warn("stop_win32_session_events(%s) missing handle!", app_hwnd)
        except:
            log.error("stop_win32_session_events", exc_info=True)

    def tray_event(self, wParam, lParam):
        x, y = win32api.GetCursorPos()
        size = win32api.GetSystemMetrics(win32con.SM_CXSMICON)
        self.recalculate_geometry(x, y, size, size)
        if lParam in BALLOON_EVENTS:
            debug("WM_TRAY_EVENT: %s", BALLOON_EVENTS.get(lParam))
        elif lParam==win32con.WM_MOUSEMOVE:
            debug("WM_TRAY_EVENT: WM_MOUSEMOVE")
            if self.mouseover_cb:
                self.mouseover_cb(x, y)
        elif lParam in BUTTON_MAP:
            debug("WM_TRAY_EVENT: click %s", BUTTON_MAP.get(lParam))
        else:
            log.warn("WM_TRAY_EVENT: unknown event: %s / %s", wParam, lParam)


    #****************************************************************
    # Events detection (screensaver / login / logout)
    def detect_win32_session_events(self, app_hwnd):
        """
        Use pywin32 to receive session notification events.
        """
        if app_hwnd is None:
            if self.tray_widget is None:
                #probably closing down, don't warn
                return
            log.warn("detect_win32_session_events(%s) missing handle!", app_hwnd)
            return
        try:
            debug("detect_win32_session_events(%s)", app_hwnd)
            #register our interest in those events:
            #http://timgolden.me.uk/python/win32_how_do_i/track-session-events.html#isenslogon
            #http://stackoverflow.com/questions/365058/detect-windows-logout-in-python
            #http://msdn.microsoft.com/en-us/library/aa383841.aspx
            #http://msdn.microsoft.com/en-us/library/aa383828.aspx
            win32ts.WTSRegisterSessionNotification(app_hwnd, win32ts.NOTIFY_FOR_THIS_SESSION)
            #catch all events: http://wiki.wxpython.org/HookingTheWndProc
            self.old_win32_proc = win32gui.SetWindowLong(app_hwnd, win32con.GWL_WNDPROC, self.MyWndProc)
        except Exception, e:
            log.error("failed to hook session notifications: %s", e)

    def MyWndProc(self, hWnd, msg, wParam, lParam):
        assert hWnd==self.getHWND(), "invalid hwnd: %s (expected %s)" % (hWnd, self.getHWND())
        if msg in IGNORE_EVENTS:
            debug("%s: %s / %s", IGNORE_EVENTS.get(msg), wParam, lParam)
        elif msg==WM_TRAY_EVENT:
            self.tray_event(wParam, lParam)
        elif msg==win32con.WM_ACTIVATEAPP:
            debug("WM_ACTIVATEAPP focus changed: %s / %s", wParam, lParam)
        else:
            log.warn("unexpected message: %s / %s / %s", KNOWN_WM_EVENTS.get(msg, msg), wParam, lParam)
        # Pass all messages to the original WndProc
        try:
            return win32gui.CallWindowProc(self.old_win32_proc, hWnd, msg, wParam, lParam)
        except Exception, e:
            log.error("error delegating call: %s", e)
