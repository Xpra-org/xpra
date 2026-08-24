# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from collections.abc import Container

from xpra.platform.win32 import constants as win32con
from xpra.platform.win32.common import (
    WINEVENTPROC, EnumWindowsProc,
    SetWinEventHook, UnhookWinEvent, EnumWindows, IsWindowVisible,
)
from xpra.util.env import envint
from xpra.os_util import gi_import
from xpra.log import Logger

log = Logger("win32", "focus")

GLib = gi_import("GLib")

# the window events we hook are system-wide: coalesce the burst of z-order
# changes that a single user action generates before walking the whole desktop:
STACKING_DELAY = envint("XPRA_WIN32_STACKING_DELAY", 50)


def get_hwnd_stacking(hwnds: Container[int]) -> tuple[int, ...]:
    """
    Those of the given windows that are visible, from the topmost one down.
    `EnumWindows` walks the desktop's children in z-order.
    """
    found: list[int] = []

    def enum_windows_cb(hwnd: int, _lparam: int) -> bool:
        if hwnd in hwnds and IsWindowVisible(hwnd):
            found.append(hwnd)
        return True

    EnumWindows(EnumWindowsProc(enum_windows_cb), 0)
    return tuple(found)


class Win32WindowStackingWatcher:
    """
    Watches the desktop z-order and feeds the bottom-to-top window order
    to the `window` subsystem.

    This is an OS concern rather than a toolkit one: all it needs is the `HWND`
    that every client window backend exposes via `get_window_handle`,
    so it works with the native win32 backend and with the GTK one.
    """

    def __init__(self, window_client):
        self.window = window_client
        self.hook = None
        self.callback = None
        self.stacking_timer = 0

    def setup(self) -> None:
        # whether the server wants a stacking order is only known after the handshake:
        self.window.client.after_handshake(self.do_setup)

    def do_setup(self, *args) -> None:
        log("do_setup%s server_window_stacking=%s", args, self.window.server_window_stacking)
        if not self.window.server_window_stacking or self.hook:
            return
        # keep a reference to the ctypes callback:
        # the hook calls into it for as long as it is installed
        self.callback = WINEVENTPROC(self.win_event)
        # `idProcess=0`: reordering top-level windows is reported against the desktop window,
        # which belongs to another process - so this hook cannot be narrowed down to ours.
        # `EVENT_OBJECT_CREATE` .. `EVENT_OBJECT_REORDER` is a contiguous range,
        # so a single hook also covers the windows appearing and disappearing from the z-order
        self.hook = SetWinEventHook(win32con.EVENT_OBJECT_CREATE, win32con.EVENT_OBJECT_REORDER,
                                    None, self.callback, 0, 0, win32con.WINEVENT_OUTOFCONTEXT)
        log("SetWinEventHook(EVENT_OBJECT_CREATE..REORDER)=%s", self.hook)
        if not self.hook:
            self.callback = None
            log.warn("Warning: failed to hook window z-order events")
            log.warn(" the window stacking order will not be synchronized")
            return
        # ensure the server gets the initial order:
        self.update_stacking()

    def cleanup(self) -> None:
        log("cleanup() hook=%s", self.hook)
        self.cancel_stacking_timer()
        if hook := self.hook:
            self.hook = None
            UnhookWinEvent(hook)
            # `self.callback` is deliberately kept alive:
            # events queued before the hook was removed can still be delivered

    # noinspection PyUnusedLocal
    def win_event(self, hook, event: int, hwnd: int, obj_id: int, child_id: int,
                  thread_id: int, timestamp: int) -> None:
        # skip the events emitted for the controls *within* a window
        # (menu items, tooltips, carets, ..): only whole windows move in the z-order.
        # reorders are reported against the desktop window using `OBJID_CLIENT`,
        # so only the child id can be matched for those:
        if child_id != win32con.CHILDID_SELF:
            return
        if event != win32con.EVENT_OBJECT_REORDER and obj_id != win32con.OBJID_WINDOW:
            return
        log("win_event%s", (hook, event, hwnd, obj_id, child_id, thread_id, timestamp))
        # this fires for every window shown, hidden or restacked on the desktop, ours or not:
        # `update_stacking` works out whether anything of ours has actually moved
        if not self.stacking_timer:
            self.stacking_timer = GLib.timeout_add(STACKING_DELAY, self.stacking_timeout)

    def cancel_stacking_timer(self) -> None:
        if st := self.stacking_timer:
            self.stacking_timer = 0
            GLib.source_remove(st)

    def stacking_timeout(self) -> bool:
        self.stacking_timer = 0
        self.update_stacking()
        return False

    def update_stacking(self) -> None:
        # `send_window_stacking` only emits a packet if the order has changed:
        self.window.send_window_stacking(self.get_window_stacking(self.window))

    @staticmethod
    def get_window_stacking(window_client) -> tuple[int, ...]:
        hwnd_to_wid: dict[int, int] = {}
        for wid, window in window_client._id_to_window.items():
            if window.is_tray():
                # a system tray icon is not a window of its own: it has no `HWND`
                continue
            hwnd = window.get_window_handle()
            if hwnd:
                hwnd_to_wid[hwnd] = wid
        # `EnumWindows` returns the topmost window first, the server expects the reverse:
        hwnds = get_hwnd_stacking(hwnd_to_wid)
        stacking = tuple(hwnd_to_wid[hwnd] for hwnd in reversed(hwnds) if hwnd in hwnd_to_wid)
        log("hwnd stacking=%s, window stacking=%s", hwnds, stacking)
        return stacking
