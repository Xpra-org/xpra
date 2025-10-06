#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2025 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.util.gobject import to_gsignals
from xpra.wayland.compositor import WaylandCompositor
from xpra.server.base import ServerBase
from xpra.os_util import gi_import
from xpra.log import Logger

log = Logger("server", "wayland")

GObject = gi_import("GObject")
GLib = gi_import("GLib")


class WaylandSeamlessServer(GObject.GObject, ServerBase):
    __gsignals__ = to_gsignals(ServerBase.__signals__)

    def __init__(self):
        GObject.GObject.__init__(self)
        ServerBase.__init__(self)
        self.session_type: str = "wayland"
        self.compositor = WaylandCompositor()
        self.wayland_fd_source = 0

    @staticmethod
    def get_display_size():
        return 1024, 768

    @staticmethod
    def get_display_description() -> str:
        return "Wayland Display (details missing)"

    def wayland_io_callback(self, fd: int, condition):
        log("wayland_io_callback%s", (fd, condition))
        if condition & GLib.IO_IN:
            self.compositor.process_events()
        elif condition & GLib.IO_ERR:
            log.error("Error: IO_ERR on wayland compositor fd %i", fd)
        return GLib.SOURCE_CONTINUE

    def do_run(self) -> None:
        log("WaylandSeamlessServer.do_run()")
        self.compositor.initialize()
        fd = self.compositor.get_event_loop_fd()
        conditions = GLib.IO_IN | GLib.IO_ERR
        log("wayland compositor event loop fd=%i", fd)
        self.wayland_fd_source = GLib.unix_fd_add_full(GLib.PRIORITY_DEFAULT, fd, conditions, self.wayland_io_callback)
        super().do_run()

    def cleanup(self):
        fd = self.wayland_fd_source
        if fd:
            self.wayland_fd_source = 0
            GLib.source_remove(fd)
        c = self.compositor
        if c:
            c.cleanup()
            self.compositor = None


GObject.type_register(WaylandSeamlessServer)
