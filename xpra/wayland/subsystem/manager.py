# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
from collections.abc import Callable

from xpra.server.subsystem.stub import StubSubsystem
from xpra.scripts.server import VFBStartResult
from xpra.log import Logger

log = Logger("server", "wayland")


class WaylandManager(StubSubsystem):
    """
    Owns the in-process wayland compositor and its display-socket binding.

    This is the wayland analogue of `XvfbManager`: it allocates the display
    name. Because the compositor creates its socket inside the target user's
    `$XDG_RUNTIME_DIR`, `setup_display()` must run *after* privileges have been
    dropped (see `do_run_server`), so that the socket is owned by that user.
    """
    __slots__ = ("compositor", "displayfd", "socket_name", "started")
    PREFIX = "wayland"

    def __init__(self, server=None):
        super().__init__(server)
        self.compositor = None
        self.displayfd = ""
        self.socket_name = ""
        self.started = False

    def init(self, opts) -> None:
        self.displayfd = str(opts.displayfd or "")
        # `init` is dispatched to every subsystem (and also called explicitly
        # from do_run_server), so guard against re-creating the compositor:
        if self.compositor is None:
            from xpra.wayland.compositor import WaylandCompositor
            self.compositor = WaylandCompositor()

    def setup_display(self, progress: Callable) -> VFBStartResult:
        # bind the wayland display socket *only* (no backend start yet). The
        # backend is started later from `WaylandSeamlessServer.setup()`, after
        # `init_subsystems()` has connected the display/window subsystems to
        # the compositor - otherwise the initial `new-output` event would fire
        # with no Python listener attached and be lost.
        progress(40, "binding the wayland display socket")
        socket_name = self.bind_display()
        log("wayland display socket bound to WAYLAND_DISPLAY=%r", socket_name)
        # drive the session-dir rename + daemon log update, same wiring as
        # XvfbManager (consumed by session-files via the "display-name" signal):
        self.emit("display-name", socket_name)
        return VFBStartResult(None, 0, {}, socket_name, (), int(self.displayfd or 0))

    def bind_display(self) -> str:
        # idempotent: the compositor's wl_display_add_socket_auto() picks the
        # first free `wayland-N` slot and is only invoked once.
        if not self.socket_name:
            self.socket_name = self.compositor.add_socket()
            os.environ["WAYLAND_DISPLAY"] = self.socket_name
        return self.socket_name

    def start_display(self) -> None:
        # idempotent: start the wlroots backend; this emits `new-output` for
        # the initial output, which is delivered to the display subsystem
        # (already connected via `init_subsystems`).
        if not self.started:
            self.compositor.start_backend()
            self.started = True

    def cleanup(self) -> None:
        if c := self.compositor:
            self.compositor = None
            c.cleanup()
