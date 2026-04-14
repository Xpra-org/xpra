# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from time import monotonic
from typing import Any

from xpra.net.common import Packet, BACKWARDS_COMPATIBLE
from xpra.net.packet_type import POINTER_BUTTON
from xpra.util.system import is_Wayland
from xpra.util.objects import typedict
from xpra.util.env import envint, envbool
from xpra.client.base.stub import StubClientMixin
from xpra.log import Logger

log = Logger("window", "pointer")

SKIP_DUPLICATE_BUTTON_EVENTS: bool = envbool("XPRA_SKIP_DUPLICATE_BUTTON_EVENTS", True)
POLL_POINTER = envint("XPRA_POLL_POINTER", 0)


class WindowPointer(StubClientMixin):
    def __init__(self):
        self.server_input_devices = None
        self._button_state = {}
        self.poll_pointer_timer = 0
        self.poll_pointer_position = -1, -1

    def cleanup(self) -> None:
        log("WindowClient.cleanup()")
        # the protocol has been closed, it is now safe to close all the windows:
        # (cleaner and needed when we run embedded in the client launcher)
        self.cancel_poll_pointer_timer()
        log("WindowClient.cleanup() done")

    def get_info(self) -> dict[str, Any]:
        return {
            "buttons": self._button_state,
        }

    def parse_server_capabilities(self, c: typedict) -> bool:
        self.server_input_devices = c.strget("input-devices")
        if POLL_POINTER:
            if is_Wayland():
                log.warn("Warning: pointer polling is unlikely to work under Wayland")
                log.warn(" and may cause problems")
            self.poll_pointer_timer = self.timeout_add(POLL_POINTER, self.poll_pointer)
        return True

    def cancel_poll_pointer_timer(self) -> None:
        if ppt := self.poll_pointer_timer:
            self.poll_pointer_timer = 0
            self.source_remove(ppt)

    def _process_pointer_position(self, packet: Packet) -> None:
        wid = packet.get_wid()
        x = packet.get_i16(2)
        y = packet.get_i16(3)
        if len(packet) >= 6:
            rx = packet.get_i16(4)
            ry = packet.get_i16(5)
        else:
            rx, ry = -1, -1
        cx, cy = self.get_mouse_position()
        start_time = monotonic()
        log("process_pointer_position: %i,%i (%i,%i relative to wid %i) - current position is %i,%i",
            x, y, rx, ry, wid, cx, cy)
        size = 10
        for i, w in self._id_to_window.items():
            # not all window implementations have this method:
            # (but GLClientWindow does)
            show_pointer_overlay = getattr(w, "show_pointer_overlay", None)
            if show_pointer_overlay:
                if i == wid:
                    value = rx, ry, size, start_time
                else:
                    value = None
                show_pointer_overlay(value)

    def send_button(self, device_id: int, wid: int, button: int, pressed: bool,
                    pointer, modifiers, buttons, props) -> None:
        pressed_state = self._button_state.get(button, False)
        if SKIP_DUPLICATE_BUTTON_EVENTS and pressed_state == pressed:
            log("button action: unchanged state, ignoring event")
            return
        # map wheel buttons via translation table to support inverted axes:
        server_button = button
        if button > 3:
            server_button = self.wheel_map.get(button, -1)
        server_buttons = []
        for b in buttons:
            if b > 3:
                sb = self.wheel_map.get(button)
                if not sb:
                    continue
                b = sb
            server_buttons.append(b)
        self._button_state[button] = pressed
        if "pointer-button" in self.server_packet_types or not BACKWARDS_COMPATIBLE:
            props = props or {}
            if modifiers is not None:
                props["modifiers"] = modifiers
            props["buttons"] = server_buttons
            if server_button != button:
                props["raw-button"] = button
            if server_buttons != buttons:
                props["raw-buttons"] = buttons
            seq = self.next_pointer_sequence(device_id)
            packet = [POINTER_BUTTON, device_id, seq, wid, server_button, pressed, pointer, props]
        else:
            if server_button == -1:
                return
            packet = ["button-action", wid, server_button, pressed, pointer, modifiers, server_buttons]
            if props:
                packet += list(props.values())
        log("button packet: %s", packet)
        self.send_positional(*packet)

    @staticmethod
    def scale_pointer(pointer) -> tuple[int, int]:
        # subclass may scale this:
        # return int(pointer[0]/self.xscale), int(pointer[1]/self.yscale)
        return round(pointer[0]), round(pointer[1])

    def send_input_devices(self, fmt: str, input_devices: dict[int, dict[str, Any]]) -> None:
        assert self.server_input_devices
        self.send("input-devices", fmt, input_devices)

    def poll_pointer(self) -> bool:
        pos = self.get_mouse_position()
        if pos != self.poll_pointer_position:
            self.poll_pointer_position = pos
            device_id = -1
            wid = 0
            log(f"poll_pointer() updated position: {pos}")
            self.send_mouse_position(device_id, wid, pos)
        return True

    def init_authenticated_packet_handlers(self) -> None:
        self.add_packets("pointer-position", "pointer-grab", "pointer-ungrab", main_thread=True)
