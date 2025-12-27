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

log = Logger("win32")

GLib = gi_import("GLib")


class WindowsMessageSource(GLib.Source):
    """Custom GLib source that processes Windows messages"""

    def __init__(self):
        super().__init__()
        self.msg = MSG()
        self.main_loop = None
        # Set high priority so Windows messages are processed promptly
        self.set_priority(GLib.PRIORITY_HIGH)

    def prepare(self):
        # log("prepare()")
        """Check if messages are available without blocking"""
        # Return (ready, timeout)
        # timeout=-1 means wait indefinitely, 0 means don't wait
        has_message = PeekMessageW(
            byref(self.msg),
            None,  # All windows
            0, 0,  # All messages
            win32con.PM_NOREMOVE  # Don't remove from queue
        )
        # If messages available, dispatch immediately (timeout=0)
        # If no messages, check again in 10ms (timeout=10)
        timeout = 0 if has_message else 10
        return has_message != 0, timeout

    def check(self):
        """Check if source is ready to dispatch"""
        has_message = PeekMessageW(
            byref(self.msg),
            None,
            0, 0,
            win32con.PM_NOREMOVE
        )
        # log("check() PeekMessage(..)=%s", has_message != 0)
        return has_message != 0

    def dispatch(self, callback, user_data):
        """
        Process a LIMITED number of Windows messages per call
        This allows GLib main loop to run and Windows to do background work
        """
        max_messages = 5
        processed = 0
        pmsg = byref(self.msg)
        while processed < max_messages and PeekMessageW(pmsg, None, 0, 0, win32con.PM_REMOVE):
            msgid = self.msg.message
            # log("dispatch message=%s", WM_MESSAGES.get(msgid, msgid))
            if msgid == win32con.WM_QUIT:
                # Quit the GLib main loop when Windows sends WM_QUIT
                if self.main_loop:
                    self.main_loop.quit()
                return False

            TranslateMessage(pmsg)
            DispatchMessageW(pmsg)
            processed += 1

        # Continue running this source
        return True


def process_windows_messages():
    """Process Windows messages - called by GLib timer"""
    msg = MSG()
    processed = 0
    max_per_call = 5

    while processed < max_per_call and PeekMessageW(byref(msg), None, 0, 0, win32con.PM_REMOVE):
        msgid = msg.message
        # log("Timer dispatch: %s", WM_MESSAGES.get(msgid, msgid))
        if msgid == win32con.WM_QUIT:
            return False  # Stop timer

        TranslateMessage(byref(msg))
        DispatchMessageW(byref(msg))
        processed += 1

    return True  # Continue timer


def inject_windows_message_source(main_loop) -> int:
    context = main_loop.get_context()
    win_source = WindowsMessageSource()
    win_source.main_loop = main_loop  # Store reference for WM_QUIT handling
    main_loop._win_message_source = win_source  # Store reference ot prevent garbage collection

    return win_source.attach(context)
