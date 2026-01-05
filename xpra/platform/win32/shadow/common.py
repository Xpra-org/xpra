# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
from _ctypes import byref
from ctypes import c_ulong, create_unicode_buffer
from ctypes.wintypes import RECT
from typing import Any

from xpra.platform.win32.common import (
    FindWindowA, IsWindowVisible, GetWindowThreadProcessId, GetWindowTextLengthW,
    GetWindowTextW, GetWindowRect, EnumWindows, EnumWindowsProc, EnumDisplayMonitors, GetMonitorInfo,
)
from xpra.util.env import envbool
from xpra.log import Logger

shapelog = Logger("shape")


def get_shape_rectangles(logit=False) -> list:
    # get the list of windows
    log_fn = shapelog.debug
    if logit or envbool("XPRA_SHAPE_DEBUG", False):
        log_fn = shapelog.info
    taskbar = FindWindowA("Shell_TrayWnd", None)
    log_fn("taskbar window=%#x", taskbar)
    ourpid = os.getpid()
    log_fn("our pid=%i", ourpid)
    rectangles = []

    # noinspection PyUnusedLocal
    def enum_windows_cb(hwnd: int, lparam: int) -> bool:
        if not IsWindowVisible(hwnd):
            log_fn("skipped invisible window %#x", hwnd)
            return True
        pid = c_ulong()
        thread_id = GetWindowThreadProcessId(hwnd, byref(pid))
        if pid == ourpid:
            log_fn("skipped our own window %#x", hwnd)
            return True
        # skipping IsWindowEnabled check
        length = GetWindowTextLengthW(hwnd)
        buf = create_unicode_buffer(length + 1)
        if GetWindowTextW(hwnd, buf, length + 1) > 0:
            window_title = buf.value
        else:
            window_title = ''
        log_fn("get_shape_rectangles() found window '%s' with pid=%i and thread id=%i", window_title, pid, thread_id)
        rect = RECT()
        if GetWindowRect(hwnd, byref(rect)) == 0:  # NOSONAR
            log_fn("GetWindowRect failure")
            return True
        left, top, right, bottom = int(rect.left), int(rect.top), int(rect.right), int(rect.bottom)
        if right < 0 or bottom < 0:
            log_fn("skipped offscreen window at %ix%i", right, bottom)
            return True
        if hwnd == taskbar:
            log_fn("skipped taskbar")
            return True
        # dirty way:
        if window_title == 'Program Manager':
            return True
        # this should be the proper way using GetTitleBarInfo (but does not seem to work)
        # import ctypes
        # from ctypes.windll.user32 import GetTitleBarInfo
        # from ctypes.wintypes import (DWORD, RECT)
        # class TITLEBARINFO(ctypes.Structure):
        #    pass
        # TITLEBARINFO._fields_ = [
        #    ('cbSize', DWORD),
        #    ('rcTitleBar', RECT),
        #    ('rgstate', DWORD * 6),
        # ]
        # ti = TITLEBARINFO()
        # ti.cbSize = sizeof(ti)
        # GetTitleBarInfo(hwnd, byref(ti))
        # if ti.rgstate[0] & win32con.STATE_SYSTEM_INVISIBLE:
        #    log("skipped system invisible window")
        #    return True
        w = right - left
        h = bottom - top
        log_fn("shape(%s - %#x)=%s", window_title, hwnd, (left, top, w, h))
        if w <= 0 and h <= 0:
            log_fn("skipped invalid window size: %ix%i", w, h)
            return True
        if left == -32000 and top == -32000:
            # there must be a better way of skipping those - I haven't found it
            log_fn("skipped special window")
            return True
        # now clip rectangle:
        if left < 0:
            left = 0
            w = right
        if top < 0:
            top = 0
            h = bottom
        rectangles.append((left, top, w, h))
        return True

    EnumWindows(EnumWindowsProc(enum_windows_cb), 0)
    log_fn("get_shape_rectangles()=%s", rectangles)
    return sorted(rectangles)


def get_monitors() -> list[dict[str, Any]]:
    monitors = []
    for m in EnumDisplayMonitors():
        mi = GetMonitorInfo(m)
        monitors.append(mi)
    return monitors
