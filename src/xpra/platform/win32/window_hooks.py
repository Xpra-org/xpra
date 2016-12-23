# This file is part of Xpra.
# Copyright (C) 2011 Serviware (Arthur Huillet, <ahuillet@serviware.com>)
# Copyright (C) 2010-2016 Antoine Martin <antoine@devloop.org.uk>
# Copyright (C) 2008, 2010 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.util import envbool
from xpra.log import Logger
log = Logger("win32", "window", "util")
vlog = Logger("verbose")

import win32con         #@UnresolvedImport
import win32api         #@UnresolvedImport
import ctypes
from ctypes import c_int, c_long
from ctypes.wintypes import POINT
from xpra.platform.win32.wndproc_events import WNDPROC_EVENT_NAMES

#use ctypes to ensure we call the "W" version:
SetWindowLong = ctypes.windll.user32.SetWindowLongW
CallWindowProc = ctypes.windll.user32.CallWindowProcW
WndProcType = ctypes.WINFUNCTYPE(c_int, c_long, c_int, c_int, c_int)


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


class Win32Hooks(object):

    def __init__(self, hwnd):
        self._hwnd = hwnd
        self._message_map = {}
        self.max_size = None
        if HOOK_MINMAXINFO:
            self.add_window_event_handler(win32con.WM_GETMINMAXINFO, self.on_getminmaxinfo)
        try:
            #we only use this code for resizable windows, so use SM_C?SIZEFRAME:
            self.frame_width = win32api.GetSystemMetrics(win32con.SM_CXSIZEFRAME)
            self.frame_height = win32api.GetSystemMetrics(win32con.SM_CYSIZEFRAME)
            self.caption_height = win32api.GetSystemMetrics(win32con.SM_CYCAPTION);
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
        self._newwndproc = WndProcType(self._wndproc)
        self._oldwndproc = SetWindowLong(self._hwnd, win32con.GWL_WNDPROC, self._newwndproc)

    def on_getminmaxinfo(self, hwnd, msg, wparam, lparam):
        if self.max_size and lparam:
            info = ctypes.cast(lparam, ctypes.POINTER(MINMAXINFO)).contents
            width, height = self.max_size
            style = win32api.GetWindowLong(hwnd, win32con.GWL_STYLE)
            if style & win32con.WS_BORDER:
                fw, fh = self.frame_width, self.frame_height
            else:
                fw, fh = 0, 0
            w = width + fw*2
            h = height + self.caption_height + fh*2
            for v in (info.ptMaxSize, info.ptMaxTrackSize):
                if v and v.x>0:
                    w = min(w, v.x)
                if v and v.y>0:
                    h = min(h, v.y)
            point  = POINT(w, h)
            info.ptMaxSize       = point
            info.ptMaxTrackSize  = point
            log("on_getminmaxinfo window=%#x max_size=%s, frame=%sx%s, minmaxinfo size=%sx%s", hwnd, self.max_size, fw, fh, w, h)
            return 0
        log("on_getminmaxinfo window=%#x max_size=%s", hwnd, self.max_size)

    def cleanup(self, *args):
        log("cleanup%s", args)
        self._message_map = {}
        #since we assume the window is closed, restoring the wnd proc may be redundant here:
        if not self._oldwndproc or not self._hwnd:
            return
        try:
            SetWindowLong(self._hwnd, win32con.GWL_WNDPROC, self._oldwndproc)
            self._oldwndproc = None
            self._hwnd = None
        except:
            log.error("cleanup", exc_info=True)

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
            v = CallWindowProc(self._oldwndproc, hwnd, msg, wparam, lparam)
            vlog("_wndproc%s return value=%s", (hwnd, msg, wparam, lparam), v)
        return v
