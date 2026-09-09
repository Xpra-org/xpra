# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.util.env import envint
from xpra.server.window.model import WindowModelStub
from xpra.os_util import gi_import
from xpra.log import Logger

log = Logger("wayland", "window")

GLib = gi_import("GLib")

# How long to wait for a window source to send a frame before answering its callback ourselves.
# Wayland applications generally throttle their rendering on these callbacks, so one we never
# answer stalls the application - unlike X11 clients, which are not told when their updates
# have been sent and therefore never wait for us. So this is deliberately short:
FRAME_TIMEOUT = envint("XPRA_WAYLAND_FRAME_TIMEOUT", 1000)


class FrameCallbackModel(WindowModelStub):
    """
    Answers the wayland frame callbacks of a single surface.

    `wlr_surface_send_frame_done` drains every callback queued on the surface it is
    given, and nothing propagates them down the surface tree, so this cannot be shared
    between a toplevel and its subsurfaces: each one answers for itself, through the
    `surface` and `display` properties its model publishes.
    """

    def __init__(self):
        super().__init__()
        # non-zero while a commit has brought damage that no window source has sent yet:
        self._damage_frame_timer = 0

    def mark_damage_frame_pending(self) -> None:
        """
        Record that a commit has brought damage which has not been sent to any client yet.

        `wlr_surface_send_frame_done` drains every callback queued on the surface, not just
        the one belonging to the commit we are answering. So until this damage has been sent,
        an empty commit must not answer for it: the application would be free to render ahead
        of us, which is what the batching in `send_delayed_regions` is there to prevent.
        """
        if not self._damage_frame_timer:
            # the deadline belongs to the oldest callback we still owe an answer for,
            # so a client which keeps committing must not be able to push it back for ever:
            self._damage_frame_timer = GLib.timeout_add(FRAME_TIMEOUT, self.damage_frame_timeout)

    def cancel_damage_frame_timer(self) -> None:
        if dft := self._damage_frame_timer:
            self._damage_frame_timer = 0
            GLib.source_remove(dft)

    def damage_frame_timeout(self) -> bool:
        self._damage_frame_timer = 0
        # nothing sent this frame - there may well be no client which can see this window -
        # so answer the callback anyway rather than leaving the application waiting for it:
        log("no damage was sent for %s within %ims", self, FRAME_TIMEOUT)
        self.acknowledge_changes()
        return False

    def acknowledge_changes(self) -> None:
        if not self._managed:
            return
        self.cancel_damage_frame_timer()
        if surface := self._gproperties.get("surface"):
            surface.frame_done()
        if display := self._gproperties.get("display"):
            display.flush_clients()

    def acknowledge_empty_changes(self) -> None:
        """ Answer a commit which brought no damage of its own - see `mark_damage_frame_pending` """
        if self._damage_frame_timer:
            return
        self.acknowledge_changes()
