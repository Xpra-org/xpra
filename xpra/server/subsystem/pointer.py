# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.
# pylint: disable-msg=E1101

from typing import Any

from xpra.util.env import envbool
from xpra.net.common import Packet
from xpra.server.subsystem.stub_server_mixin import StubServerMixin
from xpra.log import Logger

pointerlog = Logger("pointer")

INPUT_SEQ_NO = envbool("XPRA_INPUT_SEQ_NO", False)


class PointerServer(StubServerMixin):
    """
    Mixin for servers that handle pointer devices
    (mouse, etc)
    """

    def __init__(self):
        self.input_devices = "auto"
        self.input_devices_format = None
        self.input_devices_data = None
        self.pointer_sequence = {}
        self.last_mouse_user = None

    def get_server_features(self, _source=None) -> dict[str, Any]:
        return {
            "input-devices": self.input_devices,
            "pointer.relative": True,  # assumed available in 5.0.3
        }

    def _move_pointer(self, device_id, wid, pos, *args) -> None:
        raise NotImplementedError()

    def _adjust_pointer(self, proto, device_id, wid: int, pointer):
        # the window may not be mapped at the same location by the client:
        ss = self.get_server_source(proto)
        if not hasattr(ss, "update_mouse"):
            return pointer
        window = self._id_to_window.get(wid)
        if ss and window:
            ws = ss.get_window_source(wid)
            if ws:
                mapped_at = ws.mapped_at
                pos = self.get_window_position(window)
                if mapped_at and pos:
                    wx, wy = pos
                    cx, cy = mapped_at[:2]
                    if wx != cx or wy != cy:
                        dx, dy = wx - cx, wy - cy
                        if dx != 0 or dy != 0:
                            px, py = pointer[:2]
                            ax, ay = px + dx, py + dy
                            pointerlog(
                                "client %2i: server window position: %12s, client window position: %24s, pointer=%s, adjusted: %s",
                                # noqa: E501
                                ss.counter, pos, mapped_at, pointer, (ax, ay))
                            return [ax, ay] + list(pointer[2:])
        return pointer

    def process_mouse_common(self, proto, device_id: int, wid: int, opointer, props=None):
        pointer = self._adjust_pointer(proto, device_id, wid, opointer)
        if not pointer:
            return None
        if self.do_process_mouse_common(proto, device_id, wid, pointer, props):
            return pointer
        return None

    def do_process_mouse_common(self, proto, device_id: int, wid: int, pointer, props) -> bool:
        return True

    def _process_pointer_button(self, proto, packet: Packet) -> None:
        pointerlog("process_pointer_button(%s, %s)", proto, packet)
        if self.readonly:
            return
        ss = self.get_server_source(proto)
        if not hasattr(ss, "update_mouse"):
            return
        ss.user_event()
        self.last_mouse_user = ss.uuid
        self.set_ui_driver(ss)
        device_id = packet.get_i64(1)
        seq = packet.get_u64(2)
        wid = packet.get_wid(3)
        button = packet.get_u8(4)
        pressed = packet.get_bool(5)
        pointer = packet.get_ints(6)
        props = packet.get_dict(7)
        if device_id >= 0:
            # highest_seq = self.pointer_sequence.get(device_id, 0)
            # if INPUT_SEQ_NO and 0<=seq<=highest_seq:
            #    pointerlog(f"dropped outdated sequence {seq}, latest is {highest_seq}")
            #    return
            self.pointer_sequence[device_id] = seq
        self.do_process_button_action(proto, device_id, wid, button, pressed, pointer, props)

    def _process_button_action(self, proto, packet: Packet) -> None:
        pointerlog("process_button_action(%s, %s)", proto, packet)
        if self.readonly:
            return
        ss = self.get_server_source(proto)
        if not hasattr(ss, "update_mouse"):
            return
        ss.user_event()
        self.last_mouse_user = ss.uuid
        self.set_ui_driver(ss)
        wid = packet.get_wid(1)
        button = packet.get_u8(2)
        pressed = packet.get_bool(3)
        pointer = packet.get_ints(4)
        modifiers = packet.get_strs(5)
        device_id = 0
        props = {
            "modifiers": modifiers,
        }
        if len(packet) >= 7:
            props["buttons"] = 6
        self.do_process_button_action(proto, device_id, wid, button, pressed, pointer, props)

    def do_process_button_action(self, proto, device_id, wid, button, pressed, pointer, props) -> None:
        """ all servers should implement this method """

    def _update_modifiers(self, proto, wid, modifiers) -> None:
        """ servers subclasses may change the modifiers state """

    def _process_pointer(self, proto, packet: Packet) -> None:
        # v5 packet format
        pointerlog("_process_pointer(%s, %s) readonly=%s, ui_driver=%s",
                   proto, packet, self.readonly, self.ui_driver)
        if self.readonly:
            return
        ss = self.get_server_source(proto)
        if not hasattr(ss, "update_mouse"):
            return
        device_id = packet.get_i64(1)
        seq = packet.get_u64(2)
        wid = packet.get_wid(3)
        pdata = packet.get_ints(4)
        props = packet.get_dict(5)
        if device_id >= 0:
            highest_seq = self.pointer_sequence.get(device_id, 0)
            if INPUT_SEQ_NO and 0 <= seq <= highest_seq:
                pointerlog(f"dropped outdated sequence {seq}, latest is {highest_seq}")
                return
            self.pointer_sequence[device_id] = seq
        pointer = pdata[:2]
        if len(pdata) >= 4:
            ss.mouse_last_relative_position = pdata[2:4]
        ss.mouse_last_position = pointer
        if self.ui_driver and self.ui_driver != ss.uuid:
            return
        ss.user_event()
        self.last_mouse_user = ss.uuid
        if self.process_mouse_common(proto, device_id, wid, pdata, props):
            modifiers = props.get("modifiers")
            if modifiers is not None:
                self._update_modifiers(proto, wid, modifiers)

    def _process_pointer_position(self, proto, packet: Packet) -> None:
        pointerlog("_process_pointer_position(%s, %s) readonly=%s, ui_driver=%s",
                   proto, packet, self.readonly, self.ui_driver)
        if self.readonly:
            return
        ss = self.get_server_source(proto)
        if not hasattr(ss, "update_mouse"):
            return
        wid = packet.get_wid()
        pdata = packet.get_ints(2)
        modifiers = packet.get_strs(3)
        pointer = pdata[:2]
        if len(pdata) >= 4:
            ss.mouse_last_relative_position = pdata[2:4]
        ss.mouse_last_position = pointer
        if self.ui_driver and self.ui_driver != ss.uuid:
            return
        ss.user_event()
        self.last_mouse_user = ss.uuid
        props: dict[str, Any] = {}
        device_id = -1
        if len(packet) >= 6:
            device_id = packet[5]
        if self.process_mouse_common(proto, device_id, wid, pdata, props):
            self._update_modifiers(proto, wid, modifiers)

    ######################################################################
    # input devices:
    def _process_input_devices(self, _proto, packet: Packet) -> None:
        self.input_devices_format = packet.get_str(1)
        self.input_devices_data = packet.get_dict(2)
        from xpra.util.str_fn import print_nested_dict
        pointerlog("client %s input devices:", self.input_devices_format)
        print_nested_dict(self.input_devices_data, print_fn=pointerlog)
        self.setup_input_devices()

    def setup_input_devices(self) -> None:
        """
        subclasses can override this method
        the x11 servers use this to map devices
        """

    def init_packet_handlers(self) -> None:
        self.add_packets(
            # mouse:
            "pointer-button", "pointer",
            "pointer-position",  # pre v5
            # setup:
            "input-devices",
            main_thread=True
        )
        self.add_packet_handler("set-keyboard-sync-enabled", self._process_keyboard_sync_enabled_status, True)
        self.add_packet_handler("button-action", self._process_button_action, True)  # pre v5
