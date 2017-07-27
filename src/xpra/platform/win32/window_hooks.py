# This file is part of Xpra.
# Copyright (C) 2011 Serviware (Arthur Huillet, <ahuillet@serviware.com>)
# Copyright (C) 2010-2017 Antoine Martin <antoine@devloop.org.uk>
# Copyright (C) 2008, 2010 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.util import envbool
from xpra.log import Logger
log = Logger("win32", "window", "util")
vlog = Logger("verbose")

import ctypes
from ctypes.wintypes import POINT
from xpra.platform.win32.wndproc_events import WNDPROC_EVENT_NAMES
from xpra.platform.win32 import constants as win32con
from xpra.platform.win32.common import WNDPROC


user32 = ctypes.WinDLL("user32", use_last_error=True)
GetSystemMetrics = user32.GetSystemMetrics
#use ctypes to ensure we call the "W" version:
SetWindowLongW = user32.SetWindowLongW
GetWindowLongW = user32.GetWindowLongW
CallWindowProcW = user32.CallWindowProcW


class MINMAXINFO(ctypes.Structure):
    _fields_ = [
                ("ptReserved",      POINT),
                ("ptMaxSize",       POINT),
                ("ptMaxPosition",   POINT),
                ("ptMinTrackSize",  POINT),
                ("ptMaxTrackSize",  POINT),
               ]


#loosely based on this recipe:
#http://code.activestate.com/recipes/334779-pygtk-win32-extension-empower-gtk-with-win32-windo/
#and this WM_GETMINMAXINFO ctypes code:
#https://github.com/Mozillion/SublimeSpeech/blob/master/lib/dragonfly/windows/dialog_base.py
#only hardcoded for handling WM_GETMINMAXINFO,
#but should be pretty easy to tweak if needed.

HOOK_MINMAXINFO = envbool("XPRA_WIN32_MINMAXINFO", True)
HOOK_MINMAXINFO_OVERRIDE = envbool("XPRA_WIN32_MINMAXINFO_OVERRIDE", True)


class Win32Hooks(object):

    def __init__(self, hwnd):
        self._hwnd = hwnd
        self._message_map = {}
        self.max_size = None
        self.min_size = None
        if HOOK_MINMAXINFO:
            self.add_window_event_handler(win32con.WM_GETMINMAXINFO, self.on_getminmaxinfo)
        try:
            #we only use this code for resizable windows, so use SM_C?SIZEFRAME:
            self.frame_width = GetSystemMetrics(win32con.SM_CXSIZEFRAME)
            self.frame_height = GetSystemMetrics(win32con.SM_CYSIZEFRAME)
            self.caption_height = GetSystemMetrics(win32con.SM_CYCAPTION);
        except:
            self.frame_width = 4
            self.frame_height = 4
            self.caption_height = 26
        log("Win32Hooks: window frame size is %sx%s", self.frame_width, self.frame_height)
        log("Win32Hooks: message_map=%s", self._message_map)
        self._oldwndproc = None

    def add_window_event_handler(self, event, handler):
        self._message_map[event] = handler

    def setup(self):
        assert self._oldwndproc is None
        self._newwndproc = WNDPROC(self._wndproc)
        self._oldwndproc = SetWindowLongW(self._hwnd, win32con.GWL_WNDPROC, self._newwndproc)

    def on_getminmaxinfo(self, hwnd, msg, wparam, lparam):
        if (self.min_size or self.max_size) and lparam:
            info = ctypes.cast(lparam, ctypes.POINTER(MINMAXINFO)).contents
            style = GetWindowLongW(hwnd, win32con.GWL_STYLE)
            dw, dh = 0, 0
            if style & win32con.WS_BORDER:
                fw, fh = self.frame_width, self.frame_height
                dw = fw*2
                dh = self.caption_height + fh*2
                log("on_getminmaxinfo window=%#x min_size=%s, max_size=%s, frame=%sx%s", hwnd, self.min_size, self.max_size, fw, fh)
            if self.min_size:
                minw, minh = self.min_size
                minw += dw
                minh += dh
                if not HOOK_MINMAXINFO_OVERRIDE:
                    for v in (info.ptMinTrackSize, ):
                        if v and v.x>0:
                            minw = max(minw, v.x)
                        if v and v.y>0:
                            minh = max(minh, v.y)
                point  = POINT(minw, minh)
                info.ptMinSize       = point
                info.ptMinTrackSize  = point
                log("on_getminmaxinfo actual min_size=%ix%i", minw, minh)
            if self.max_size:
                maxw, maxh = self.max_size
                maxw += dw
                maxh += dh
                if not HOOK_MINMAXINFO_OVERRIDE:
                    for v in (info.ptMaxSize, info.ptMaxTrackSize):
                        if v and v.x>0:
                            maxw = min(maxw, v.x)
                        if v and v.y>0:
                            maxh = min(maxh, v.y)
                point  = POINT(maxw, maxh)
                info.ptMaxSize       = point
                info.ptMaxTrackSize  = point
                log("on_getminmaxinfo actual max_size=%ix%i", maxw, maxh)
            return 0
        log("on_getminmaxinfo window=%#x min_size=%s, max_size=%s", hwnd, self.min_size, self.max_size)

    def cleanup(self, *args):
        log("cleanup%s", args)
        self._message_map = {}
        #since we assume the window is closed, restoring the wnd proc may be redundant here:
        if not self._oldwndproc or not self._hwnd:
            return
        try:
            SetWindowLongW(self._hwnd, win32con.GWL_WNDPROC, self._oldwndproc)
            self._oldwndproc = None
            self._hwnd = None
        except:
            log.error("Error: window hooks cleanup failure", exc_info=True)

    def _wndproc(self, hwnd, msg, wparam, lparam):
        event_name = WNDPROC_EVENT_NAMES.get(msg, msg)
        callback = self._message_map.get(msg)
        vlog("_wndproc%s event name=%s, callback=%s", (hwnd, msg, wparam, lparam), event_name, callback)
        v = None
        if callback:
            #run our callback
            try:
                v = callback(hwnd, msg, wparam, lparam)
                vlog("%s%s=%s", callback, (hwnd, msg, wparam, lparam), v)
            except Exception as e:
                log.error("Error: callback %s failed:", callback)
                log.error(" %s", e)
        #if our callback doesn't define the return value, use the default handler:
        if v is None:
            v = CallWindowProcW(self._oldwndproc, hwnd, msg, wparam, lparam)
            vlog("_wndproc%s return value=%s", (hwnd, msg, wparam, lparam), v)
        return v
