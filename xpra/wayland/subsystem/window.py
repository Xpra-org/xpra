# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.net.common import Packet
from xpra.server.subsystem.window import WindowServer
from xpra.util.objects import typedict
from xpra.log import Logger

focuslog = Logger("server", "wayland", "focus")


class WaylandWindowServer(WindowServer):

    def _process_window_map(self, _proto, packet: Packet) -> None:
        wid = packet.get_wid()
        window = self.get_window(wid)
        surface = self.server.get_surface(wid)
        if not (window and surface):
            return
        w = packet.get_i16(4)
        h = packet.get_i16(5)
        surface.resize(w, h)
        self.server.compositor.flush()
        self.refresh_window(window)

    def do_process_window_configure(self, _proto, wid, config: typedict) -> None:
        window = self.get_window(wid)
        surface = self.server.get_surface(wid)
        if not (window and surface):
            return
        geometry = config.inttupleget("geometry")
        if geometry:
            w, h = geometry[2:4]
            surface.resize(w, h)
            self.server.compositor.flush()
            self.refresh_window(window)

    def _focus(self, _server_source, wid: int, modifiers) -> None:
        server = self.server
        focuslog("_focus(%s, %s) current focus=%i", wid, modifiers, server.focused)
        keyboard = server.subsystems.get("keyboard")
        if modifiers is not None and keyboard:
            keyboard.update_keyboard_modifiers(modifiers)
        if server.focused == wid:
            return
        for window_id, state in {
            server.focused: False,
            wid: True,
        }.items():
            if not window_id:
                if state and keyboard and keyboard.device:
                    keyboard.device.focus(0)
                continue
            window = server.get_window(window_id)
            surface = server.get_surface(window_id)
            focuslog("focus: wid=%#x, state=%s, window=%s, surface=%s", window_id, state, window, surface)
            if window and surface:
                surface.focus(state)
                if state and (ptr := surface.xdg_surface_ptr):
                    if keyboard and keyboard.device:
                        keyboard.device.focus(ptr)
        server.focused = wid
        server.compositor.flush()

    def get_focus(self) -> int:
        return self.server.focused
