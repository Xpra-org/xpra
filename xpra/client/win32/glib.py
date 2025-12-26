# This file is part of Xpra.
# Copyright (C) 2025 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import win32con
from ctypes import byref
from ctypes.wintypes import MSG

from xpra.platform.win32.common import PeekMessageW, TranslateMessage, DispatchMessageW
from xpra.os_util import gi_import
from xpra.log import Logger

GLib = gi_import("GLib")

log = Logger("win32")


class WindowsMessageSource(GLib.Source):
    """Custom GLib source that processes Windows messages"""

    def __init__(self):
        super().__init__()
        self.msg = MSG()
        self.main_loop = None

    def prepare(self):
        log("prepare()")
        """Check if messages are available without blocking"""
        # Return (ready, timeout)
        # timeout=-1 means wait indefinitely, 0 means don't wait
        has_message = PeekMessageW(
            byref(self.msg),
            None,  # All windows
            0, 0,  # All messages
            win32con.PM_NOREMOVE  # Don't remove from queue
        )
        return has_message != 0, 0

    def check(self):
        """Check if source is ready to dispatch"""
        has_message = PeekMessageW(
            byref(self.msg),
            None,
            0, 0,
            win32con.PM_NOREMOVE
        )
        log("check() PeekMessage(..)=%s", has_message != 0)
        return has_message != 0

    def dispatch(self, callback, user_data):
        """Process Windows messages"""
        log("dispatch(..)")
        while PeekMessageW(byref(self.msg), None, 0, 0, win32con.PM_REMOVE):
            log("dispatch msg=%s", self.msg)
            if self.msg.message == win32con.WM_QUIT:
                # Quit the GLib main loop when Windows sends WM_QUIT
                if self.main_loop:
                    self.main_loop.quit()
                return False

            TranslateMessage(byref(self.msg))
            DispatchMessageW(byref(self.msg))

        # Continue running this source
        return True


def inject_windows_message_source(main_loop):
    context = main_loop.get_context()
    win_source = WindowsMessageSource()
    win_source.main_loop = main_loop  # Store reference for WM_QUIT handling
    win_source.attach(context)
