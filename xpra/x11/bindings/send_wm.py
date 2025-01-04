# This file is part of Xpra.
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2012 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from typing import Final

from xpra.x11.bindings.window import constants, X11WindowBindings
from xpra.log import Logger

log = Logger("x11", "focus")

X11Window = X11WindowBindings()

CurrentTime: Final[int] = constants["CurrentTime"]
SubstructureNotifyMask: Final[int] = constants["SubstructureNotifyMask"]
SubstructureRedirectMask: Final[int] = constants["SubstructureRedirectMask"]


def send_wm_take_focus(xid: int, timestamp: int = CurrentTime) -> None:
    log("sending WM_TAKE_FOCUS: %#x, X11 timestamp=%r", xid, int(timestamp or 0))
    if timestamp < 0:
        timestamp = 0
    elif timestamp > 0xFFFFFFFF:
        raise OverflowError(f"invalid time: {timestamp:x}")
    elif timestamp > 0x7FFFFFFF:
        timestamp = int(0x100000000 - timestamp)
        if timestamp >= 0x80000000:
            timestamp -= 0x80000000
    X11Window.sendClientMessage(xid, xid, False, 0,
                                "WM_PROTOCOLS",
                                "WM_TAKE_FOCUS", timestamp)


def send_wm_delete_window(xid: int, timestamp: int = CurrentTime) -> None:
    log("sending WM_DELETE_WINDOW to %#x", xid)
    X11Window.sendClientMessage(xid, xid, False, 0,
                                "WM_PROTOCOLS",
                                "WM_DELETE_WINDOW",
                                timestamp)


def send_wm_workspace(root_xid: int, xid: int, workspace: int = 0, timestamp: int = CurrentTime) -> None:
    event_mask = SubstructureNotifyMask | SubstructureRedirectMask
    X11Window.sendClientMessage(root_xid, xid, False, event_mask,
                                "_NET_WM_DESKTOP",
                                workspace,
                                timestamp)


def send_wm_request_frame_extents(root_xid: int, xid: int, timestamp: int = CurrentTime) -> None:
    event_mask = SubstructureNotifyMask | SubstructureRedirectMask
    X11Window.sendClientMessage(root_xid, xid, False, event_mask,
                                "_NET_REQUEST_FRAME_EXTENTS",
                                0,
                                timestamp)
