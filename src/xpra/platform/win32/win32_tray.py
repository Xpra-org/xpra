#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2011-2014 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

# Augments the win32_NotifyIcon "system tray" support class
# with methods for integrating with win32_balloon and the popup menu

import win32con, win32api        #@UnresolvedImport

from xpra.log import Logger
log = Logger("tray", "win32")

from xpra.platform.win32.win32_events import get_win32_event_listener, BALLOON_EVENTS
from xpra.platform.win32.win32_NotifyIcon import win32NotifyIcon, WM_TRAY_EVENT, BUTTON_MAP
from xpra.client.tray_base import TrayBase


class Win32Tray(TrayBase):

    def __init__(self, *args):
        TrayBase.__init__(self, *args)
        self.default_icon_extension = "ico"
        self.default_icon_name = "xpra.ico"
        icon_filename = self.get_tray_icon_filename(self.default_icon_filename)
        self.tray_widget = win32NotifyIcon(self.tooltip, self.click_cb, self.exit_cb, None, icon_filename)
        #now let's try to hook the session notification
        el = get_win32_event_listener()
        el.add_event_callback(WM_TRAY_EVENT, self.tray_event)

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
        log("Win32Tray.cleanup() tray_widget=%s", self.tray_widget)
        if self.tray_widget:
            self.tray_widget.close()
            self.tray_widget = None
        log("Win32Tray.cleanup() ended")

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


    def tray_event(self, wParam, lParam):
        x, y = win32api.GetCursorPos()
        size = win32api.GetSystemMetrics(win32con.SM_CXSMICON)
        self.recalculate_geometry(x, y, size, size)
        if lParam in BALLOON_EVENTS:
            log("WM_TRAY_EVENT: %s", BALLOON_EVENTS.get(lParam))
        elif lParam==win32con.WM_MOUSEMOVE:
            log("WM_TRAY_EVENT: WM_MOUSEMOVE")
            if self.mouseover_cb:
                self.mouseover_cb(x, y)
        elif lParam in BUTTON_MAP:
            log("WM_TRAY_EVENT: click %s", BUTTON_MAP.get(lParam))
        else:
            log.warn("WM_TRAY_EVENT: unknown event: %s / %s", wParam, lParam)
