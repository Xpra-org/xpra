# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

"""
The minimized / maximized state of a native window, tracked from its `WM_MOVE` and `WM_SIZE` messages,
and what the server must be told about it - mirroring the GTK3 client:
* minimizing unmaps the window (`minimized` signal -> `window-unmap` with `iconified=True`),
* restoring it maps it again (`mapped` signal -> `map-window` with `iconified=False`),
  even when it is restored straight back to maximized and its size has not changed,
* maximizing / restoring an already visible window resizes its backing and sends the state with the geometry
  (`resized` signal), or on its own if the size did not change (`maximized` signal).

This module makes no Win32 API calls, so that it can be tested on any platform.
"""

from xpra.log import Logger

log = Logger("client", "window")

# `WM_SIZE` `wparam` values:
SIZE_RESTORED = 0
SIZE_MINIMIZED = 1
SIZE_MAXIMIZED = 2
SIZE_MAXSHOW = 3
SIZE_MAXHIDE = 4

# the position `WM_MOVE` reports for a minimized window:
MINIMIZED_POSITION = -32000


def set_minimized(window) -> None:
    if window.minimized:
        return
    window.minimized = True
    window.state_updates["iconified"] = True
    window.emit("minimized")


def handle_move(window, x: int, y: int) -> bool:
    """
    Returns `True` if the `WM_MOVE` message has been fully handled.
    """
    if x == MINIMIZED_POSITION and y == MINIMIZED_POSITION:
        set_minimized(window)
        return True
    window.x = x
    window.y = y
    # when restoring a minimized window, `WM_MOVE` comes first:
    # the `map-window` packet sent from `WM_SIZE` will carry the new position
    if not window.minimized:
        window.emit("moved")
    return False


def handle_size(window, wparam: int, width: int, height: int) -> bool:
    """
    Returns `True` if the `WM_SIZE` message has been fully handled.
    """
    if wparam == SIZE_MINIMIZED:
        set_minimized(window)
        return True
    if wparam in (SIZE_MAXSHOW, SIZE_MAXHIDE):
        return True
    if wparam not in (SIZE_MAXIMIZED, SIZE_RESTORED):
        log("unexpected WM_SIZE wparam %#x", wparam)
        return False
    maximized = wparam == SIZE_MAXIMIZED
    if maximized != window.maximized:
        window.maximized = maximized
        window.state_updates["maximized"] = maximized
    deiconified = window.minimized
    if deiconified:
        window.minimized = False
        window.state_updates["iconified"] = False
    resized = bool(window.backing) and (width, height) != (window.width, window.height)
    if resized:
        window.update_backing_render_size(width, height)
        window.width = width
        window.height = height
    if deiconified:
        # `map-window` carries the geometry, the backing's client properties and the state updates:
        window.emit("mapped")
    elif resized:
        window.emit("resized")
    elif "maximized" in window.state_updates:
        window.emit("maximized")
    return False
