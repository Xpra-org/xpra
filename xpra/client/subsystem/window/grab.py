# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
from typing import Any

from xpra.net.common import Packet
from xpra.net.packet_type import WINDOW_DISMISS
from xpra.util.objects import typedict
from xpra.util.env import envbool
from xpra.client.base.stub import StubClientSubsystem
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
# ask the server to release its grabs when the window which had the grab loses focus:
FORCE_UNGRAB = envbool("XPRA_FORCE_UNGRAB", True)


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


class WindowGrab(StubClientSubsystem):
    __slots__ = ()
    # these mixins are all composed into a single `WindowClient` instance,
    # which is the subsystem registered as `window`: declaring the prefix here
    # too keeps each mixin usable (and testable) on its own
    PREFIX = "window"
    SLOT_NAMES = ("_window_with_grab", "pointer_grabbed", "server_window_dismiss", "server_force_ungrab")

    def __init__(self):
        self._window_with_grab = None
        self.pointer_grabbed = None
        self.server_window_dismiss = False
        self.server_force_ungrab = False

    def parse_server_capabilities(self, c: typedict) -> bool:
        self.server_window_dismiss = c.boolget("window.dismiss")
        self.server_force_ungrab = c.boolget("force_ungrab")
        return True

    def get_info(self) -> dict[str, Any]:
        return {
            "grabbed": self._window_with_grab or 0,
            "pointer-grab": self.pointer_grabbed or 0,
        }

    def is_grabbed(self, wid: int) -> bool:
        return bool(wid) and self._window_with_grab == wid

    def grab_lost(self) -> None:
        self._window_with_grab = None

    def window_grab(self, wid: int, window) -> None:
        """
        grab the pointer and keyboard for this window,
        the native part is done by the window itself, if it can (`do_window_grab`)
        """
        log("window_grab(%#x, %s)", wid, window)
        if do_window_grab := getattr(window, "do_window_grab", None):
            do_window_grab()
        self._window_with_grab = wid

    def window_ungrab(self, window=None) -> None:
        """ release the grab, `window` defaults to the window which has it """
        wid = self._window_with_grab
        if window is None and wid:
            window = self.get_window(wid)
        log("window_ungrab(%s) grabbed=%s", window, wid)
        if do_window_ungrab := getattr(window, "do_window_ungrab", None):
            do_window_ungrab()
        self._window_with_grab = None

    def do_force_ungrab(self, wid: int) -> None:
        log("do_force_ungrab(%#x) enabled=%s, server support=%s", wid, FORCE_UNGRAB, self.server_force_ungrab)
        if not FORCE_UNGRAB or not self.server_force_ungrab or self.client.readonly or self.client.server_readonly:
            return
        # ungrab via dedicated server packet:
        self.client.send_force_ungrab(wid)

    def dismiss_popups(self) -> None:
        # Release our local grabs immediately, even with an older server or in readonly mode.
        self.window_ungrab()
        self.pointer_grabbed = None
        if keyboard := self.get_subsystem("keyboard"):
            keyboard.grabbed = False
        if self.client.readonly or self.client.server_readonly:
            return
        if not self.server_window_dismiss:
            log.warn("Warning: the server does not support dismissing popup windows")
            return
        # Use a snapshot: unmapping a popup removes its client window asynchronously.
        for wid, window in tuple(self._id_to_window.items()):
            if window.is_OR() and not window.is_tray():
                self.send(WINDOW_DISMISS, wid)

    def _process_grab(self, packet: Packet) -> None:
        wid = packet.get_wid()
        window = self.get_window(wid)
        log("grabbing %#x: %s", wid, window)
        if window:
            self.window_grab(wid, window)

    def _process_ungrab(self, packet: Packet) -> None:
        wid = packet.get_wid()
        window = self.get_window(wid)
        log("ungrabbing %#x: %s", wid, window)
        self.window_ungrab()

    ######################################################################
    # packets:
    def init_authenticated_packet_handlers(self) -> None:
        self.add_packets("window-grab", "window-ungrab", main_thread=True)
