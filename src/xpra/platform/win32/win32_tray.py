#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2011-2013 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

# Augments the win32_NotifyIcon "system tray" support class
# with methods for integrating with win32_balloon and the popup menu

import tempfile

from xpra.platform.win32.win32_NotifyIcon import win32NotifyIcon
from xpra.client.tray_base import TrayBase, log, debug


class Win32Tray(TrayBase):

    def __init__(self, menu, tooltip, icon_filename, size_changed_cb, click_cb, mouseover_cb, exit_cb):
        TrayBase.__init__(self, menu, tooltip, icon_filename, size_changed_cb, click_cb, mouseover_cb, exit_cb)
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
        #TODO: use native code somehow to avoid saving to file
        import os
        from gtk import gdk
        try:
            _, filename = tempfile.mkstemp(".ico", "temp")
            debug("set_icon_from_data%s using temporary file %s", ("%s pixels" % len(pixels), has_alpha, w, h, rowstride), filename)
            tray_icon = gdk.pixbuf_new_from_data(pixels, gdk.COLORSPACE_RGB, has_alpha, 8, w, h, rowstride)
            tray_icon.save(filename, "ico")
            self.set_icon(filename)
        finally:
            os.unlink(filename)

    def set_icon(self, iconPathName):
        if self.tray_widget:
            self.tray_widget.set_icon(iconPathName)

    def set_blinking(self, on):
        if self.tray_widget:
            self.tray_widget.set_blinking(on)


    def stop_win32_session_events(self, app_hwnd):
        if app_hwnd is None:
            log.warn("stop_win32_session_events(%s) missing handle!", app_hwnd)
            return
        try:
            import win32ts                                        #@UnresolvedImport
            win32ts.WTSUnRegisterSessionNotification(app_hwnd)
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
            WM_TRAYICON = win32con.WM_USER + 20
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
                    debug("WM_DESTROY, restoring call handler %s", self.oldWndProc)
                    win32api.SetWindowLong(app_hwnd, win32con.GWL_WNDPROC, self.oldWndProc)
                elif msg==win32con.WM_COMMAND:
                    debug("WM_COMMAND")
                elif msg==WM_TRAYICON:
                    debug("WM_TRAYICON")
                    if lParam==NIN_BALLOONSHOW:
                        debug("NIN_BALLOONSHOW")
                    if lParam==NIN_BALLOONHIDE:
                        debug("NIN_BALLOONHIDE")
                        self.balloon_click_callback = None
                    elif lParam==NIN_BALLOONTIMEOUT:
                        debug("NIN_BALLOONTIMEOUT")
                    elif lParam==NIN_BALLOONUSERCLICK:
                        debug("NIN_BALLOONUSERCLICK, balloon_click_callback=%s", self.balloon_click_callback)
                        if self.balloon_click_callback:
                            self.balloon_click_callback()
                            self.balloon_click_callback = None
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
