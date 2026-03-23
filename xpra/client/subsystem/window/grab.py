# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
from typing import Any

from xpra.net.common import Packet
from xpra.util.objects import typedict
from xpra.client.base.stub import StubClientMixin
from xpra.log import Logger

log = Logger("window", "grab")


def get_grab_defs(grab_str: str) -> dict[str, list[str]]:
    grab_defs: dict[str, list[str]] = {}
    for s in grab_str.split(","):
        if not s:
            continue
        parts = s.split(":")
        if len(parts) == 1:
            grab_defs.setdefault("*", []).append(s)
        else:
            grab_defs.setdefault(parts[0], []).append(parts[1])
    return grab_defs


OR_FORCE_GRAB_STR: str = os.environ.get("XPRA_OR_FORCE_GRAB", "DIALOG:sun-awt-X11")
OR_FORCE_GRAB = get_grab_defs(OR_FORCE_GRAB_STR)


def should_force_grab(metadata: typedict) -> bool:
    if not OR_FORCE_GRAB:
        return False
    window_types = metadata.get("window-type", [])
    wm_class = metadata.strtupleget("class-instance", ("", ""), 2, 2)
    c = ""
    if wm_class:
        c = wm_class[0]
    if c:
        for window_type, force_wm_classes in OR_FORCE_GRAB.items():
            # ie: DIALOG : ["sun-awt-X11"]
            if window_type == "*" or window_type in window_types:
                for wmc in force_wm_classes:
                    if wmc == "*" or c and c.startswith(wmc):
                        return True
    return False


class WindowGrab(StubClientMixin):

    def __init__(self):
        self._window_with_grab = None
        self.pointer_grabbed = None

    def get_info(self) -> dict[str, Any]:
        return {
            "grabbed": self._window_with_grab or 0,
            "pointer-grab": self.pointer_grabbed or 0,
        }

    def window_grab(self, wid: int, _window) -> None:
        log.warn(f"Warning: window grab not implemented in {self.client_type}")
        self._window_with_grab = wid

    def window_ungrab(self) -> None:
        log.warn(f"Warning: window ungrab not implemented in {self.client_type}")
        self._window_with_grab = None

    def do_force_ungrab(self, wid: int) -> None:
        log("do_force_ungrab(%#x)", wid)
        # ungrab via dedicated server packet:
        self.send_force_ungrab(wid)

    def _process_pointer_grab(self, packet: Packet) -> None:
        wid = packet.get_wid()
        window = self.get_window(wid)
        log("grabbing %#x: %s", wid, window)
        if window:
            self.window_grab(wid, window)

    def _process_pointer_ungrab(self, packet: Packet) -> None:
        wid = packet.get_wid()
        window = self.get_window(wid)
        log("ungrabbing %#x: %s", wid, window)
        self.window_ungrab()

    ######################################################################
    # packets:
    def init_authenticated_packet_handlers(self) -> None:
        self.add_packets("pointer-grab", "pointer-ungrab", main_thread=True)
