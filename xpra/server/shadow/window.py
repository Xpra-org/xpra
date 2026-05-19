# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.server.subsystem.window import WindowServer
from xpra.util.objects import typedict
from xpra.net.common import Packet
from xpra.net.constants import ConnectionMessage
from xpra.net.packet_type import WINDOW_CREATE
from xpra.log import Logger

log = Logger("server", "window")


class ShadowWindowServer(WindowServer):
    """
    Window subsystem for shadow servers (whole-screen capture).

    Shadow servers present the user's existing display as one or more
    capture windows. The variant server still owns the refresh state
    machine (`start_refresh` / `stop_refresh` / `refresh_timer`) and
    the capture lifecycle, because those are platform-specific.
    """

    def load_existing_windows(self) -> None:
        mmap_sub = self.get_subsystem("mmap")
        if mmap_sub:
            mmap_sub.min_size = 1024 * 1024 * 4 * 2
        for i, model in enumerate(self.server.make_capture_window_models()):
            log(f"load_existing_windows() root window model {i} : {model}")
            self._add_new_window(model)
            # at least big enough for 2 frames of BGRX pixel data:
            w, h = model.get_dimensions()
            if mmap_sub:
                mmap_sub.min_size = max(mmap_sub.min_size, w * h * 4 * 2)

    def send_initial_windows(self, ss, sharing: bool = False) -> None:
        log("send_initial_windows(%s, %s) will send: %s", ss, sharing, self._id_to_window)
        for wid, window in self._id_to_window.items():
            w, h = window.get_dimensions()
            client_props = self.client_properties.get(wid, {}).get(ss.uuid, {})
            ss.new_window(WINDOW_CREATE, wid, window, 0, 0, w, h, client_props)

    def _add_new_window(self, window) -> None:
        self._add_new_window_common(window)
        self._send_new_window_packet(window)

    def _send_new_window_packet(self, window) -> None:
        geometry = window.get_geometry()
        self._do_send_new_window_packet(WINDOW_CREATE, window, geometry)

    @staticmethod
    def get_window_position(_window) -> tuple[int, int]:
        # whole-screen capture is exposed as a single (0, 0) window
        return 0, 0

    def _process_window_map(self, proto, packet: Packet) -> None:
        wid = packet.get_wid()
        x = packet.get_i16(2)
        y = packet.get_i16(3)
        w = packet.get_i16(4)
        h = packet.get_i16(5)
        window = self.get_window(wid)
        if not window:
            return
        self._window_mapped_at(proto, wid, window, (x, y, w, h))
        self.refresh_window_area(window, 0, 0, w, h)
        if len(packet) >= 7:
            self._set_client_properties(proto, wid, window, packet[6])
        # the refresh state machine lives on the variant:
        self.server.start_refresh(wid)

    def _process_window_unmap(self, proto, packet: Packet) -> None:
        wid = packet.get_wid()
        window = self.get_window(wid)
        if not window:
            return
        self._window_mapped_at(proto, wid, window)
        # TODO: deal with more than one window / more than one client
        # and stop refresh if all the windows are unmapped everywhere
        if len(self.window_sources()) <= 1 and len(self.models()) <= 1:
            self.server.stop_refresh(wid)

    def do_process_window_configure(self, proto, wid, config: typedict) -> None:
        window = self.get_window(wid)
        if not window:
            return
        geometry = config.inttupleget("geometry")
        if geometry:
            self._window_mapped_at(proto, wid, window, geometry)
            w, h = geometry[2:4]
            self.refresh_window_area(window, 0, 0, w, h)

        properties = config.dictget("properties")
        if properties:
            self._set_client_properties(proto, wid, window, properties)

    def _process_window_close(self, proto, packet: Packet) -> None:
        wid = packet.get_wid()
        window = self.get_window(wid)
        if not window:
            return
        # FIXME: with multiple windows / clients,
        # we have to keep track of mappings!
        if len(self.models()) == 1:
            self.server.disconnect_client(proto, ConnectionMessage.DONE, "closed the only window")
