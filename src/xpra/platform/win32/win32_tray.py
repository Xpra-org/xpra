#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2011-2014 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

# Augments the win32_NotifyIcon "system tray" support class
# with methods for integrating with win32_balloon and the popup menu

import win32con         #@UnresolvedImport
import win32api         #@UnresolvedImport

from xpra.log import Logger
log = Logger("tray", "win32")

from xpra.platform.win32.win32_NotifyIcon import win32NotifyIcon
from xpra.client.tray_base import TrayBase
from xpra.platform.win32.win32_events import get_win32_event_listener


class Win32Tray(TrayBase):

    def __init__(self, *args):
        TrayBase.__init__(self, *args)
        self.calculate_offset()
        icon_filename = self.get_tray_icon_filename(self.default_icon_filename)
        self.tray_widget = win32NotifyIcon(self.tooltip, self.move_cb, self.click_cb, self.exit_cb, None, icon_filename)
        get_win32_event_listener().add_event_callback(win32con.WM_DISPLAYCHANGE, self.calculate_offset)

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
        get_win32_event_listener().remove_event_callback(win32con.WM_DISPLAYCHANGE, self.calculate_offset)
        log("Win32Tray.cleanup() ended")

    def calculate_offset(self, *args):
        #GTK returns coordinates as unsigned ints, but win32 can give us negative coordinates!
        self.offset_x = 0
        self.offset_y = 0
        try:
            for m in win32api.EnumDisplayMonitors(None, None):
                mi = win32api.GetMonitorInfo(m[0])
                mx1, my1, _, _ = mi['Monitor']
                self.offset_x = max(self.offset_x, -mx1)
                self.offset_y = max(self.offset_y, -my1)
        except Exception as e:
            log.warn("failed to query monitors: %s", e)
        log("calculate_offset() x=%i, y=%i", self.offset_x, self.offset_y)

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


    def move_cb(self, *args):
        x, y = win32api.GetCursorPos()
        size = win32api.GetSystemMetrics(win32con.SM_CXSMICON)
        x += self.offset_x
        y += self.offset_y
        log("move_cb%s x=%s, y=%s, size=%s", args, x, y, size)
        self.recalculate_geometry(x, y, size, size)
        if self.mouseover_cb:
            self.mouseover_cb(x, y)
