# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.client.subsystem.window import WindowClient


class TerminalWindowClient(WindowClient):
    """ Window subsystem exposing the terminal client's stacking and focus state. """
    __slots__ = ()

    def window_z(self, wid: int) -> int:
        return self.client.window_z(wid)

    def window_mapped(self, window) -> None:
        self.client.window_mapped(window)

    def raise_window(self, wid: int) -> None:
        self.client.raise_window(wid)

    def restack_window(self, wid: int, other_wid: int, above: int) -> None:
        self.client.restack_window(wid, other_wid, above)

    def focus_window(self, wid: int) -> None:
        # Keep the client's input routing and pointer synchronization in step
        # with the focus packets sent by this subsystem's update_focus().
        self.client.focus_window(wid)

    def is_focused(self, wid: int) -> bool:
        return self.client._focused == wid
