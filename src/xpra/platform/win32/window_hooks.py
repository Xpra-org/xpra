# This file is part of Xpra.
# Copyright (C) 2011 Serviware (Arthur Huillet, <ahuillet@serviware.com>)
# Copyright (C) 2010-2014 Antoine Martin <antoine@devloop.org.uk>
# Copyright (C) 2008, 2010 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.log import Logger
log = Logger("win32", "window", "util")
vlog = Logger("verbose")

import win32gui, win32con, win32api     #@UnresolvedImport
import ctypes
from ctypes.wintypes import POINT
from xpra.platform.win32.wndproc_events import WNDPROC_EVENT_NAMES


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


import os
MINMAXINFO = os.environ.get("XPRA_WIN32_MINMAXINFO", "1")=="1"


class Win32Hooks(object):

    def __init__(self, hwnd):
        self._hwnd = hwnd
        self._message_map = {}
        if MINMAXINFO:
            self._message_map[win32con.WM_GETMINMAXINFO] = self.on_getminmaxinfo
        self.max_size = None
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

    def setup(self):
        assert self._oldwndproc is None
        self._oldwndproc = win32gui.SetWindowLong(self._hwnd, win32con.GWL_WNDPROC, self._wndproc)

    def on_getminmaxinfo(self, hwnd, msg, wparam, lparam):
        if self.max_size:
            info = ctypes.cast(lparam, ctypes.POINTER(MINMAXINFO)).contents
            width, height = self.max_size
            style = win32api.GetWindowLong(hwnd, win32con.GWL_STYLE)
            if style & win32con.WS_BORDER:
                fw, fh = self.frame_width, self.frame_height
            else:
                fw, fh = 0, 0
            w = width + fw*2
            h = height + self.caption_height + fh*2
            point  = POINT(w, h)
            info.ptMaxSize       = point
            info.ptMaxTrackSize  = point
            log("on_getminmaxinfo%s max_size=%s, frame=%sx%s, minmaxinfo size=%sx%s", (hwnd, msg, wparam, lparam), self.max_size, fw, fh, w, h)
        else:
            log("on_getminmaxinfo%s max_size=%s", (hwnd, msg, wparam, lparam), self.max_size)

    def cleanup(self, *args):
        log("cleanup%s", args)
        self._message_map = {}
        #since we assume the window is closed, restoring the wnd proc may be redundant here:
        if not self._oldwndproc or not self._hwnd:
            return
        try:
            win32api.SetWindowLong(self._hwnd, win32con.GWL_WNDPROC, self._oldwndproc)
            self._oldwndproc = None
            self._hwnd = None
        except:
            log.error("cleanup", exc_info=True)

    def _wndproc(self, hwnd, msg, wparam, lparam):
        event_name = WNDPROC_EVENT_NAMES.get(msg, msg)
        callback = self._message_map.get(msg)
        vlog("_wndproc%s event name=%s, callback=%s", (hwnd, msg, wparam, lparam), event_name, callback)
        if callback:
            #run our callback
            callback(hwnd, msg, wparam, lparam)
        v = win32gui.CallWindowProc(self._oldwndproc, hwnd, msg, wparam, lparam)
        vlog("_wndproc%s return value=%s", (hwnd, msg, wparam, lparam), v)
        return v
