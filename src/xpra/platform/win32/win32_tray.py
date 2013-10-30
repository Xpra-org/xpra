#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2011-2013 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

# Augments the win32_NotifyIcon "system tray" support class
# with methods for integrating with win32_balloon and the popup menu

from xpra.platform.win32.win32_NotifyIcon import win32NotifyIcon, WM_TRAY_EVENT, BUTTON_MAP
from xpra.client.tray_base import TrayBase, log, debug


class Win32Tray(TrayBase):

    def __init__(self, menu, tooltip, icon_filename, size_changed_cb, click_cb, mouseover_cb, exit_cb):
        TrayBase.__init__(self, menu, tooltip, icon_filename, size_changed_cb, click_cb, mouseover_cb, exit_cb)
        self.default_icon_extension = "ico"
        self.default_icon_name = "xpra.ico"
        icon_filename = self.get_tray_icon_filename(icon_filename)
        self.tray_widget = win32NotifyIcon(tooltip, click_cb, exit_cb, None, icon_filename)
        #now let's try to hook the session notification
        self.detect_win32_session_events(self.getHWND())
        self.balloon_click_callback = None

    def ready(self):
        pass

    def show(self):
        pass

    def hide(self):
        pass


    def get_geometry(self):
        if self.tray_widget:
            return self.tray_widget.get_geometry()
        return None


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


    def stop_win32_session_events(self, app_hwnd):
        try:
            import win32ts, win32con, win32api          #@UnresolvedImport
            if self.old_win32_proc and app_hwnd:
                win32api.SetWindowLong(app_hwnd, win32con.GWL_WNDPROC, self.old_win32_proc)
                self.old_win32_proc = None

            if app_hwnd:
                win32ts.WTSUnRegisterSessionNotification(app_hwnd)
            else:
                log.warn("stop_win32_session_events(%s) missing handle!", app_hwnd)
        except:
            log.error("stop_win32_session_events", exc_info=True)

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
            import win32ts, win32con, win32api, win32gui        #@UnresolvedImport
            NIN_BALLOONSHOW = win32con.WM_USER + 2
            NIN_BALLOONHIDE = win32con.WM_USER + 3
            NIN_BALLOONTIMEOUT = win32con.WM_USER + 4
            NIN_BALLOONUSERCLICK = win32con.WM_USER + 5
            #register our interest in those events:
            #http://timgolden.me.uk/python/win32_how_do_i/track-session-events.html#isenslogon
            #http://stackoverflow.com/questions/365058/detect-windows-logout-in-python
            #http://msdn.microsoft.com/en-us/library/aa383841.aspx
            #http://msdn.microsoft.com/en-us/library/aa383828.aspx
            win32ts.WTSRegisterSessionNotification(app_hwnd, win32ts.NOTIFY_FOR_THIS_SESSION)
            #catch all events: http://wiki.wxpython.org/HookingTheWndProc
            def MyWndProc(hWnd, msg, wParam, lParam):
                #from the web!: WM_WTSSESSION_CHANGE is 0x02b1.
                if msg==0x02b1:
                    debug("Session state change!")
                elif msg==win32con.WM_DESTROY:
                    # Restore the old WndProc
                    debug("WM_DESTROY: %s / %s", wParam, lParam)
                elif msg==win32con.WM_COMMAND:
                    debug("WM_COMMAND")
                elif msg==WM_TRAY_EVENT:
                    if lParam==NIN_BALLOONSHOW:
                        debug("WM_TRAY_EVENT: NIN_BALLOONSHOW")
                    elif lParam==NIN_BALLOONHIDE:
                        debug("WM_TRAY_EVENT: NIN_BALLOONHIDE")
                        self.balloon_click_callback = None
                    elif lParam==NIN_BALLOONTIMEOUT:
                        debug("WM_TRAY_EVENT: NIN_BALLOONTIMEOUT")
                    elif lParam==NIN_BALLOONUSERCLICK:
                        debug("WM_TRAY_EVENT: NIN_BALLOONUSERCLICK, balloon_click_callback=%s", self.balloon_click_callback)
                        if self.balloon_click_callback:
                            self.balloon_click_callback()
                            self.balloon_click_callback = None
                    elif lParam==win32con.WM_MOUSEMOVE:
                        debug("WM_TRAY_EVENT: WM_MOUSEMOVE")
                        if self.mouseover_cb:
                            x, y = win32api.GetCursorPos()
                            self.mouseover_cb(x, y)
                    elif lParam in BUTTON_MAP:
                        debug("WM_TRAY_EVENT: %s", BUTTON_MAP.get(lParam))                        
                    else:
                        log.warn("WM_TRAY_EVENT: unknown event: %s / %s", wParam, lParam)
                elif msg==win32con.WM_ACTIVATEAPP:
                    debug("WM_ACTIVATEAPP focus changed: %s / %s", wParam, lParam)
                else:
                    log.warn("unknown win32 message: %s / %s / %s", msg, wParam, lParam)
                # Pass all messages to the original WndProc
                try:
                    return win32gui.CallWindowProc(self.old_win32_proc, hWnd, msg, wParam, lParam)
                except Exception, e:
                    log.error("error delegating call: %s", e)
            self.old_win32_proc = win32gui.SetWindowLong(app_hwnd, win32con.GWL_WNDPROC, MyWndProc)
        except Exception, e:
            log.error("failed to hook session notifications: %s", e)
