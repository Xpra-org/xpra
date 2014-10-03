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

class Win32Hooks(object):

    def __init__(self, hwnd):
        self._message_map = {
                     win32con.WM_GETMINMAXINFO:  self.on_getminmaxinfo,
                     }
        self.max_size = None
        self._oldwndproc = win32gui.SetWindowLong(hwnd, win32con.GWL_WNDPROC, self._wndproc)
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

    def on_getminmaxinfo(self, hwnd, msg, wparam, lparam):
        log("on_getminmaxinfo%s max_size=%s", (hwnd, msg, wparam, lparam), self.max_size)
        if self.max_size:
            info = ctypes.cast(lparam, ctypes.POINTER(MINMAXINFO)).contents
            width, height = self.max_size
            point  = POINT(width + self.frame_width*2, height + self.caption_height + self.frame_height*2)
            info.ptMaxSize       = point
            info.ptMaxTrackSize  = point

    def cleanup(self, *args):
        log("cleanup%s", args)
        self._message_map = {}
        #no need to restore old wndproc since we assume the window is closed

    def _wndproc(self, hwnd, msg, wparam, lparam):
        vlog("_wndproc%s", (hwnd, msg, wparam, lparam))
        v = win32gui.CallWindowProc(self._oldwndproc, hwnd, msg, wparam, lparam)
        callback = self._message_map.get(msg)
        vlog("_wndproc%s return value=%s, callback=%s", (hwnd, msg, wparam, lparam), v, callback)
        if callback:
            #run our callback
            callback(hwnd, msg, wparam, lparam)
        return v
