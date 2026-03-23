# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from typing import Any

from xpra.net.packet_type import WINDOW_FOCUS
from xpra.client.base.stub import StubClientMixin
from xpra.log import Logger

log = Logger("window", "focus")


class WindowFocus(StubClientMixin):

    def __init__(self):
        self.lost_focus_timer: int = 0
        self._focused = None

    def cleanup(self) -> None:
        self.cancel_lost_focus_timer()

    def get_info(self) -> dict[str, Any]:
        return {
            "focused": self._focused or 0,
        }

    ######################################################################
    # focus:
    def send_focus(self, wid: int) -> None:
        log("send_focus(%#x)", wid)
        self.send(WINDOW_FOCUS, wid, self.get_current_modifiers())

    def has_focus(self, wid: int) -> bool:
        return bool(self._focused) and self._focused == wid

    def update_focus(self, wid: int, gotit: bool) -> bool:
        focused = self._focused
        log(f"update_focus({wid:#x}, {gotit}) focused={focused}, grabbed={self._window_with_grab}")
        if gotit:
            if focused is not wid:
                self.send_focus(wid)
                self._focused = wid
            self.cancel_lost_focus_timer()
        else:
            if self._window_with_grab:
                self.window_ungrab()
                wwgrab = self._window_with_grab
                if wwgrab:
                    self.do_force_ungrab(wwgrab)
                self._window_with_grab = None
            if wid and focused and focused != wid:
                # if this window lost focus, it must have had it!
                # (catch up - makes things like OR windows work:
                # their parent receives the focus-out event)
                log(f"window {wid:#x} lost a focus it did not have!? (simulating focus before losing it)")
                self.send_focus(wid)
            if focused and not self.lost_focus_timer:
                # send the lost-focus via a timer and re-check it
                # (this allows a new window to gain focus without having to do a reset_focus)
                self.lost_focus_timer = self.timeout_add(20, self.send_lost_focus)
                self._focused = None
        return focused != self._focused

    def send_lost_focus(self) -> None:
        log("send_lost_focus() focused=%s", self._focused)
        self.lost_focus_timer = 0
        # check that a new window has not gained focus since:
        if self._focused is None:
            self.send_focus(0)

    def cancel_lost_focus_timer(self) -> None:
        lft = self.lost_focus_timer
        if lft:
            self.lost_focus_timer = 0
            self.source_remove(lft)
