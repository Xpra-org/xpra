# coding=utf8
# This file is part of Xpra.
# Copyright (C) 2012-2014 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import win32api         #@UnresolvedImport
import win32con         #@UnresolvedImport
from xpra.log import Logger
log = Logger("shadow", "win32")

from xpra.server.gtk_root_window_model import GTKRootWindowModel
from xpra.server.gtk_server_base import GTKServerBase
from xpra.server.shadow_server_base import ShadowServerBase
from xpra.platform.win32.keyboard_config import KeyboardConfig

BUTTON_EVENTS = {
                 #(button,up-or-down)  : win-event-name
                 (1, True)  : (win32con.MOUSEEVENTF_LEFTDOWN,   0),
                 (1, False) : (win32con.MOUSEEVENTF_LEFTUP,     0),
                 (2, True)  : (win32con.MOUSEEVENTF_MIDDLEDOWN, 0),
                 (2, False) : (win32con.MOUSEEVENTF_MIDDLEUP,   0),
                 (3, True)  : (win32con.MOUSEEVENTF_RIGHTDOWN,  0),
                 (3, False) : (win32con.MOUSEEVENTF_RIGHTUP,    0),
                 (4, True)  : (win32con.MOUSEEVENTF_WHEEL,      win32con.WHEEL_DELTA),
                 (5, True)  : (win32con.MOUSEEVENTF_WHEEL,      -win32con.WHEEL_DELTA),
                 }

class ShadowServer(ShadowServerBase, GTKServerBase):

    def __init__(self):
        import gtk.gdk
        ShadowServerBase.__init__(self, gtk.gdk.get_default_root_window())
        GTKServerBase.__init__(self)
        self.keycodes = {}

    def makeRootWindowModel(self):
        return GTKRootWindowModel(self.root)

    def _process_mouse_common(self, proto, wid, pointer, modifiers):
        #adjust pointer position for offset in client:
        x, y = pointer
        wx, wy = self.mapped_at[:2]
        rx, ry = x-wx, y-wy
        win32api.SetCursorPos((rx, ry))

    def get_keyboard_config(self, props):
        return KeyboardConfig()

    def fake_key(self, keycode, press):
        if keycode<=0:
            log.warn("no keycode found for %s", keycode)
            return
        #KEYEVENTF_SILENT = 0X4;
        flags = 0   #KEYEVENTF_SILENT
        if press:
            flags |= win32con.KEYEVENTF_KEYUP
        #get the scancode:
        MAPVK_VK_TO_VSC = 0
        scancode = win32api.MapVirtualKey(keycode, MAPVK_VK_TO_VSC)
        #see: http://msdn.microsoft.com/en-us/library/windows/desktop/ms646304(v=vs.85).aspx
        log("fake_key(%s, %s) calling keybd_event(%s, %s, %s, 0)", keycode, press, keycode, scancode, flags)
        win32api.keybd_event(keycode, scancode, flags, 0)

    def _process_button_action(self, proto, packet):
        wid, button, pressed, pointer, modifiers = packet[1:6]
        self._process_mouse_common(proto, wid, pointer, modifiers)
        self._server_sources.get(proto).user_event()
        event = BUTTON_EVENTS.get((button, pressed))
        if event is None:
            log.warn("no matching event found for button=%s, pressed=%s", button, pressed)
            return
        x, y = pointer
        dwFlags, dwData = event
        win32api.mouse_event(dwFlags, x, y, dwData, 0)

    def make_hello(self):
        capabilities = GTKServerBase.make_hello(self)
        capabilities["shadow"] = True
        capabilities["server_type"] = "Python/gtk2/win32-shadow"
        return capabilities

    def get_info(self, proto):
        info = GTKServerBase.get_info(self, proto)
        info["features.shadow"] = True
        info["server.type"] = "Python/gtk2/win32-shadow"
        return info
