#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2025 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os

from xpra.os_util import gi_import
from xpra.server.base import ServerBase
from xpra.util.gobject import to_gsignals
from xpra.log import Logger

log = Logger("server", "wayland")

GObject = gi_import("GObject")
GLib = gi_import("GLib")


class WaylandSeamlessServer(GObject.GObject, ServerBase):
    __gsignals__ = to_gsignals(ServerBase.__signals__)

    def __init__(self):
        os.environ.pop("DISPLAY", None)
        os.environ["GDK_BACKEND"] = "wayland"
        GObject.GObject.__init__(self)
        ServerBase.__init__(self)
        self.session_type: str = "wayland"
        self.wayland_fd_source = 0

    @property
    def compositor(self):
        # owned by the WaylandManager subsystem (created during its `init`):
        wm = self.get_subsystem("wayland")
        return wm.compositor if wm else None

    def init_subsystems(self) -> None:
        super().init_subsystems()
        self.get_subsystem("window").connect_compositor(self.compositor)
        self.get_subsystem("display").connect_compositor(self.compositor)

    def get_child_env(self) -> dict[str, str]:
        env: dict[str, str] = super().get_child_env()
        if os.environ.get("NO_AT_BRIDGE") is None:
            env["NO_AT_BRIDGE"] = "1"
        return env

    def get_clipboard_subsystem_class(self) -> type:
        from xpra.wayland.subsystem.clipboard import WaylandClipboardManager
        return WaylandClipboardManager

    @staticmethod
    def get_gtk_subsystem_class() -> type | None:
        # GTK may be enabled for clipboard, but it must not manage this display.
        return None

    def get_display_subsystem_class(self) -> type:
        from xpra.wayland.subsystem.display import WaylandDisplayManager
        return WaylandDisplayManager

    def get_keyboard_subsystem_class(self) -> type:
        from xpra.wayland.subsystem.keyboard import WaylandKeyboardManager
        return WaylandKeyboardManager

    def get_pointer_subsystem_class(self) -> type:
        from xpra.wayland.subsystem.pointer import WaylandPointerManager
        return WaylandPointerManager

    def get_window_subsystem_class(self) -> type:
        from xpra.wayland.subsystem.window import WaylandWindowServer
        return WaylandWindowServer

    @staticmethod
    def set_desktop_geometry(w: int, h: int) -> None:
        """ not implemented yet """

    def wayland_io_callback(self, fd: int, condition):
        log("wayland_io_callback%s", (fd, condition))
        if condition & (GLib.IO_ERR | GLib.IO_HUP | GLib.IO_NVAL):
            log.error("Error: wayland compositor fd %i condition %#x", fd, condition)
            self.wayland_fd_source = 0
            return GLib.SOURCE_REMOVE
        if condition & GLib.IO_IN:
            self.compositor.process_events()
        return GLib.SOURCE_CONTINUE

    def start_wayland_event_source(self) -> None:
        if self.wayland_fd_source:
            return
        fd = self.compositor.get_event_loop_fd()
        conditions = GLib.IO_IN | GLib.IO_ERR | GLib.IO_HUP | GLib.IO_NVAL
        log("wayland compositor event loop fd=%i", fd)
        self.wayland_fd_source = GLib.unix_fd_add_full(GLib.PRIORITY_DEFAULT, fd, conditions, self.wayland_io_callback)

    def setup(self) -> None:
        # the socket was bound earlier by WaylandManager.setup_display; the
        # display/window subsystems were just connected by init_subsystems.
        # Now start the backend so its initial `new-output` event reaches them.
        if wm := self.get_subsystem("wayland"):
            wm.bind_display()      # idempotent fallback
            wm.start_display()
        super().setup()

    def do_run(self) -> None:
        log("WaylandSeamlessServer.do_run()")
        self.start_wayland_event_source()
        super().do_run()

    def cleanup(self):
        # remove the event source before the compositor is destroyed
        # (WaylandManager.cleanup handles the compositor itself):
        if fd := self.wayland_fd_source:
            self.wayland_fd_source = 0
            GLib.source_remove(fd)
        super().cleanup()


GObject.type_register(WaylandSeamlessServer)
