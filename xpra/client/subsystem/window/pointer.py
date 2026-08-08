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
from xpra.client.base.stub import StubClientSubsystem
from xpra.log import Logger

log = Logger("window", "pointer")

SKIP_DUPLICATE_BUTTON_EVENTS: bool = envbool("XPRA_SKIP_DUPLICATE_BUTTON_EVENTS", True)
POLL_POINTER = envint("XPRA_POLL_POINTER", 0)


class WindowPointer(StubClientSubsystem):
    __slots__ = ()
    SLOT_NAMES = (
        "_button_state", "input_devices", "poll_pointer_position", "poll_pointer_timer", "server_input_devices",
    )

    def __init__(self):
        self.server_input_devices = None
        self._button_state = {}
        self.poll_pointer_timer = 0
        self.poll_pointer_position = -1, -1
        # XI2 device enumeration (X11-specific): read/written by the `xi2`
        # subsystem, when composed - see `xpra.client.subsystem.xi2.XI2Client`:
        self.input_devices = ""

    def init(self, opts) -> None:
        self.input_devices = opts.input_devices

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

    def get_mouse_position(self) -> tuple[int, int]:
        return self.client.get_mouse_position()

    def _process_pointer_position(self, packet: Packet) -> None:
        wid = packet.get_wid()
        x = packet.get_i16(2)
        y = packet.get_i16(3)
        if len(packet) >= 6:
            rx = packet.get_i16(4)
            ry = packet.get_i16(5)
        else:
            rx, ry = -1, -1
        log("process_pointer_position: %i,%i (%i,%i relative to wid %i)", x, y, rx, ry, wid)
        self.show_remote_pointer(wid, rx, ry)

    def _process_pointer_motion(self, packet: Packet) -> None:
        # another client moved the pointer, and the server is synchronizing it with us
        # (see the `sync` pointer capability)
        wid = packet.get_wid(3)
        pdata = packet.get_ints(4)
        props = typedict(packet.get_dict(5))
        # modern clients send the window relative position as a property,
        # older ones packed it into the pointer data:
        rel = props.inttupleget("window-position", max_items=2) or tuple(pdata[2:4])
        log("process_pointer_motion: %s (%s relative to wid %i)", pdata[:2], rel, wid)
        if len(rel) == 2:
            self.show_remote_pointer(wid, *rel)

    def _process_pointer_button(self, packet: Packet) -> None:
        # another client clicked: the position was already synchronized
        # by the `pointer-motion` packet which always precedes it
        log("process_pointer_button: %s", packet[1:])

    def _process_pointer_wheel(self, packet: Packet) -> None:
        # another client used the wheel, there is nothing to show for it
        log("process_pointer_wheel: %s", packet[1:])

    def show_remote_pointer(self, wid: int, rx: int, ry: int) -> None:
        """ show the pointer of another client (or of the shadowed display) as an overlay """
        cx, cy = self.get_mouse_position()
        log("show_remote_pointer(%i, %i, %i) current position is %i,%i", wid, rx, ry, cx, cy)
        start_time = monotonic()
        size = 10
        for i, w in self._id_to_window.items():
            # not all window implementations have this method:
            # (but GLClientWindow does)
            if show_pointer_overlay := getattr(w, "show_pointer_overlay", None):
                if i == wid:
                    value = rx, ry, size, start_time
                else:
                    value = ()
                # noinspection calling-non-callable
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
        pointer, position_props = self.get_subsystem("pointer").split_pointer_position(pointer)
        if "pointer-button" in self.get_server_packet_types() or not BACKWARDS_COMPATIBLE:
            props = dict(props or {})
            props.update(position_props)
            if modifiers is not None:
                props["modifiers"] = modifiers
            props["buttons"] = server_buttons
            if server_button != button:
                props["raw-button"] = button
            if server_buttons != buttons:
                props["raw-buttons"] = buttons
            seq = self.get_subsystem("pointer").next_pointer_sequence(device_id)
            packet = [POINTER_BUTTON, device_id, seq, wid, server_button, pressed, pointer, props]
        else:
            if server_button == -1:
                return
            packet = ["button-action", wid, server_button, pressed, pointer, modifiers, server_buttons]
            if props:
                packet += list(props.values())
        log("button packet: %s", packet)
        self.get_subsystem("pointer").send_positional(*packet)

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
            self.get_subsystem("pointer").send_mouse_position(device_id, wid, pos)
        return True

    def init_authenticated_packet_handlers(self) -> None:
        self.add_packets("pointer-position", "pointer-grab", "pointer-ungrab", main_thread=True)
        # the server sends us the pointer events of the other clients
        # when the `sync` pointer capability is enabled:
        self.add_packets("pointer-motion", "pointer-button", "pointer-wheel", main_thread=True)
