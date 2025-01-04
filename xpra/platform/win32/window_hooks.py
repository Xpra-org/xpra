# This file is part of Xpra.
# Copyright (C) 2011 Serviware (Arthur Huillet, <ahuillet@serviware.com>)
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from collections.abc import Callable
from ctypes import Structure, cast, POINTER
from ctypes.wintypes import POINT

from xpra.util.env import envbool
from xpra.common import noop
from xpra.platform.win32.wndproc_events import WNDPROC_EVENT_NAMES
from xpra.platform.win32 import constants as win32con
from xpra.platform.win32.common import WNDPROC, GetWindowLongW, SetWindowLongW, GetSystemMetrics, CallWindowProcW
from xpra.log import Logger


log = Logger("win32", "window", "util")
vlog = Logger("verbose")


class MINMAXINFO(Structure):
    _fields_ = [
        ("ptReserved", POINT),
        ("ptMaxSize", POINT),
        ("ptMaxPosition", POINT),
        ("ptMinTrackSize", POINT),
        ("ptMaxTrackSize", POINT),
    ]


# loosely based on this recipe:
# http://code.activestate.com/recipes/334779-pygtk-win32-extension-empower-gtk-with-win32-windo/
# and this WM_GETMINMAXINFO ctypes code:
# https://github.com/Mozillion/SublimeSpeech/blob/master/lib/dragonfly/windows/dialog_base.py
# only hardcoded for handling WM_GETMINMAXINFO,
# but should be pretty easy to tweak if needed.

HOOK_MINMAXINFO = envbool("XPRA_WIN32_MINMAXINFO", True)
HOOK_MINMAXINFO_OVERRIDE = envbool("XPRA_WIN32_MINMAXINFO_OVERRIDE", True)


class Win32Hooks:

    def __init__(self, hwnd: int):
        self._hwnd = hwnd
        self._message_map: dict[int, Callable[[int, int, int, int], int]] = {}
        self.max_size = (0, 0)
        self.min_size = (0, 0)
        self.frame_width = 4
        self.frame_height = 4
        self.caption_height = 26
        self._oldwndproc = None
        self._newwndproc = None
        if HOOK_MINMAXINFO:
            self.add_window_event_handler(win32con.WM_GETMINMAXINFO, self.on_getminmaxinfo)
        try:
            # we only use this code for resizable windows, so use SM_C?SIZEFRAME:
            self.frame_width = GetSystemMetrics(win32con.SM_CXSIZEFRAME)
            self.frame_height = GetSystemMetrics(win32con.SM_CYSIZEFRAME)
            self.caption_height = GetSystemMetrics(win32con.SM_CYCAPTION)
        except Exception:
            log("error querying frame attributes", exc_info=True)
        log("Win32Hooks: window frame size is %sx%s", self.frame_width, self.frame_height)
        log("Win32Hooks: message_map=%s", self._message_map)

    def add_window_event_handler(self, event: int, handler: Callable[[int, int, int, int], int]) -> None:
        self._message_map[event] = handler

    def setup(self) -> None:
        assert self._oldwndproc is None
        self._newwndproc = WNDPROC(self._wndproc)
        try:
            self._oldwndproc = SetWindowLongW(self._hwnd, win32con.GWL_WNDPROC, self._newwndproc)
        except Exception:
            log.error(f"Error setting up window hook for {self._hwnd}", exc_info=True)

    def on_getminmaxinfo(self, hwnd: int, msg, wparam: int, lparam: int) -> int:
        if (self.min_size > (0, 0) or self.max_size > (0, 0)) and lparam:
            info = cast(lparam, POINTER(MINMAXINFO)).contents
            style = GetWindowLongW(hwnd, win32con.GWL_STYLE)
            dw, dh = 0, 0
            if style & win32con.WS_BORDER:
                fw, fh = self.frame_width, self.frame_height
                dw = fw * 2
                dh = self.caption_height + fh * 2
                log("on_getminmaxinfo window=%#x min_size=%s, max_size=%s, frame=%sx%s",
                    hwnd, self.min_size, self.max_size, fw, fh)
            if self.min_size > (0, 0):
                minw, minh = self.min_size  # pylint: disable=unpacking-non-sequence
                minw += dw
                minh += dh
                if not HOOK_MINMAXINFO_OVERRIDE:
                    v = info.ptMinTrackSize
                    x = int(v.x)
                    y = int(v.y)
                    if v:
                        log("on_getminmaxinfo ptMinTrackSize=%ix%i", v.x, v.y)
                        if x > 0:
                            minw = max(minw, x)
                        if y > 0:
                            minh = max(minh, y)
                point = POINT(minw, minh)
                info.ptMinSize = point
                info.ptMinTrackSize = point
                log("on_getminmaxinfo actual min_size=%ix%i", minw, minh)
            if self.max_size > (0, 0):
                maxw, maxh = self.max_size  # pylint: disable=unpacking-non-sequence
                maxw += dw
                maxh += dh
                if not HOOK_MINMAXINFO_OVERRIDE:
                    for name, v in {
                        "ptMaxSize": info.ptMaxSize,
                        "ptMaxTrackSize": info.ptMaxTrackSize,
                    }.items():
                        if v:
                            x = int(v.x)
                            y = int(v.y)
                            log("on_getminmaxinfo %s=%ix%i", name, v.x, v.y)
                            if x > 0:
                                maxw = min(maxw, x)
                            if y > 0:
                                maxh = min(maxh, y)
                point = POINT(maxw, maxh)
                info.ptMaxSize = point
                info.ptMaxTrackSize = point
                log("on_getminmaxinfo actual max_size=%ix%i", maxw, maxh)
            return 0
        log("on_getminmaxinfo%s min_size=%s, max_size=%s",
            (hwnd, msg, wparam, lparam), self.min_size, self.max_size)
        return 0

    def cleanup(self, *args) -> None:
        log("cleanup%s", args)
        self._message_map = {}
        # since we assume the window is closed, restoring the wnd proc may be redundant here:
        if not self._oldwndproc or not self._hwnd:
            return
        with log.trap_error("Error: window hooks cleanup failure"):
            SetWindowLongW(self._hwnd, win32con.GWL_WNDPROC, self._oldwndproc)
            self._oldwndproc = None
            self._hwnd = None

    def _wndproc(self, hwnd: int, msg, wparam: int, lparam: int) -> int:
        event_name = WNDPROC_EVENT_NAMES.get(msg, msg)
        callback = self._message_map.get(msg, noop)
        vlog("_wndproc%s event name=%s, callback=%s", (hwnd, msg, wparam, lparam), event_name, callback)
        v = None
        if callback != noop:
            # run our callback
            try:
                v = callback(hwnd, msg, wparam, lparam)
                vlog("%s%s=%s", callback, (hwnd, msg, wparam, lparam), v)
            except Exception as e:
                log.error("Error: callback %s failed:", callback)
                log.estr(e)
        # if our callback doesn't define the return value, use the default handler:
        if v is None:
            v = CallWindowProcW(self._oldwndproc, hwnd, msg, wparam, lparam)
            vlog("_wndproc%s return value=%s", (hwnd, msg, wparam, lparam), v)
        return v
