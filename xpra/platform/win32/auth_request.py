# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

"""
`notify` authentication backend for MS Windows:
balloon notifications can't have action buttons,
so clicking the balloon opens a confirmation dialog instead.
"""

from time import monotonic
from collections.abc import Callable
from ctypes.wintypes import HWND, LPCWSTR, UINT, WORD, DWORD, INT

from xpra.common import noop
from xpra.util.thread import start_thread
from xpra.platform.win32 import constants as win32con
from xpra.platform.win32.common import user32
from xpra.platform.win32.balloon import notify
from xpra.platform.win32.events import NIN_BALLOONUSERCLICK
from xpra.platform.win32.NotifyIcon import win32NotifyIcon
from xpra.log import Logger

log = Logger("auth", "notify", "win32")

# undocumented, but available since Windows XP:
MessageBoxTimeoutW = user32.MessageBoxTimeoutW
MessageBoxTimeoutW.restype = INT
MessageBoxTimeoutW.argtypes = [HWND, LPCWSTR, LPCWSTR, UINT, WORD, DWORD]

DIALOG_FLAGS = win32con.MB_YESNO | win32con.MB_ICONQUESTION | win32con.MB_DEFBUTTON2 | win32con.MB_TOPMOST | win32con.MB_SETFOREGROUND


def find_tray() -> win32NotifyIcon | None:
    for tray in win32NotifyIcon.instances.values():
        if tray.hwnd:
            return tray
    return None


class TrayRequest:
    """ must be created and closed from the main thread """

    def __init__(self, summary: str, body: str, timeout: int, callback: Callable[[bool], None]):
        tray = find_tray()
        if not tray:
            raise RuntimeError("no system tray icon found")
        if tray.balloon_callback is not noop:
            raise RuntimeError("another request is already using the system tray icon")
        self.tray = tray
        self.summary = summary
        self.body = body
        self.callback = callback
        self.deadline = monotonic() + timeout
        self.clicked = False
        tray.balloon_callback = self.balloon_event
        log("TrayRequest using %s, body=%r", tray, body)
        notify(tray.hwnd, tray.app_id, summary, f"{body}\nClick here to review this request", timeout * 1000, None)

    def balloon_event(self, event: int) -> None:
        log("balloon_event(%#x) clicked=%s", event, self.clicked)
        # the balloon timeout and hide events are ignored:
        # since Windows Vista, the balloon timeout is chosen by the system and can be much shorter
        # than our own, and the notification may still be clicked from the notification center
        if event == NIN_BALLOONUSERCLICK and not self.clicked:
            self.clicked = True
            start_thread(self.confirm, "notify-auth-confirm", daemon=True)

    def confirm(self) -> None:
        # the dialog closes itself when the request times out:
        timeout_ms = max(1000, round((self.deadline - monotonic()) * 1000))
        text = f"{self.summary}\n{self.body}\n\nAllow this connection?"
        r = MessageBoxTimeoutW(0, text, "Xpra", DIALOG_FLAGS, 0, timeout_ms)
        log("MessageBoxTimeoutW(..)=%i", r)
        self.callback(r == win32con.IDYES)

    def close(self) -> None:
        tray = self.tray
        log("close() tray=%s, clicked=%s", tray, self.clicked)
        if tray.balloon_callback == self.balloon_event:
            tray.balloon_callback = noop
        if not self.clicked and tray.hwnd:
            # hide the balloon:
            notify(tray.hwnd, tray.app_id, "", "", 0, None)
