#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2011 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

# Augments the win32_NotifyIcon "system tray" support class
# with methods for integrating with win32_balloon and the popup menu

from time import monotonic
from ctypes import wintypes, byref

from xpra.platform.win32 import constants as win32con
from xpra.platform.win32.gui import EnumDisplayMonitors, GetMonitorInfo
from xpra.platform.win32.NotifyIcon import win32NotifyIcon
from xpra.platform.win32.events import get_win32_event_listener
from xpra.platform.win32.common import GetSystemMetrics, GetCursorPos
from xpra.tray_base import TrayBase
from xpra.platform.paths import get_icon_filename
from xpra.log import Logger

log = Logger("tray", "win32")


class Win32Tray(TrayBase):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.calculate_offset()
        self.default_icon_extension = "ico"
        icon_filename = get_icon_filename(self.default_icon_filename, "ico")
        self.tray_widget = win32NotifyIcon(self.app_id, title=self.tooltip,
                                           move_callback=self.move_cb,
                                           click_callback=self.click_cb,
                                           exit_callback=self.exit_cb,
                                           iconPathName=icon_filename)
        el = get_win32_event_listener()
        if el:
            el.add_event_callback(win32con.WM_DISPLAYCHANGE, self.calculate_offset)

    def show(self) -> None:
        """ we can't hide or show the tray on MS Windows """

    def hide(self) -> None:
        """ we can't hide or show the tray on MS Windows """

    def get_size(self) -> tuple[int, int]:
        w = GetSystemMetrics(win32con.SM_CXSMICON)
        h = GetSystemMetrics(win32con.SM_CYSMICON)
        return w, h

    def getHWND(self) -> int:
        if self.tray_widget is None:
            return 0
        return self.tray_widget.hwnd

    def cleanup(self) -> None:
        log("Win32Tray.cleanup() tray_widget=%s", self.tray_widget)
        if self.tray_widget:
            self.tray_widget.close()
            self.tray_widget = None
        el = get_win32_event_listener()
        if el:
            el.remove_event_callback(win32con.WM_DISPLAYCHANGE, self.calculate_offset)
        log("Win32Tray.cleanup() ended")

    def calculate_offset(self, *_args) -> None:
        # GTK returns coordinates as unsigned ints, but win32 can give us negative coordinates!
        self.offset_x = 0
        self.offset_y = 0
        try:
            for m in EnumDisplayMonitors():
                mi = GetMonitorInfo(m)
                mx1, my1, _, _ = mi['Monitor']
                self.offset_x = max(self.offset_x, -mx1)
                self.offset_y = max(self.offset_y, -my1)
        except Exception as e:
            log("EnumDisplayMonitors()", exc_info=True)
            log.warn("Warning: failed to query monitors: %s", e)
        log("calculate_offset() x=%i, y=%i", self.offset_x, self.offset_y)

    def set_tooltip(self, tooltip="") -> None:
        if self.tray_widget:
            self.tray_widget.set_tooltip(tooltip)

    def set_icon_from_data(self, pixels, has_alpha, w, h, rowstride, options=None) -> None:
        if self.tray_widget:
            self.tray_widget.set_icon_from_data(pixels, has_alpha, w, h, rowstride, options)
            self.icon_timestamp = monotonic()

    def do_set_icon_from_file(self, filename) -> None:
        if self.tray_widget:
            self.tray_widget.set_icon(filename)
            self.icon_timestamp = monotonic()

    def set_blinking(self, on: bool) -> None:
        if self.tray_widget:
            self.tray_widget.set_blinking(on)

    def get_geometry(self) -> tuple[int, int, int, int]:
        tw = self.tray_widget
        if tw:
            geom = tw.get_geometry()
            if geom:
                return geom
        return self.geometry_guess

    def move_cb(self, *args) -> None:
        pos = wintypes.POINT()
        GetCursorPos(byref(pos))
        x, y = pos.x, pos.y
        w = GetSystemMetrics(win32con.SM_CXSMICON)
        h = GetSystemMetrics(win32con.SM_CYSMICON)
        x += self.offset_x
        y += self.offset_y
        log("move_cb%s x=%s, y=%s, size=%i, %i", args, x, y, w, h)
        self.recalculate_geometry(x, y, w, h)
        if self.mouseover_cb:
            self.mouseover_cb(x, y)
