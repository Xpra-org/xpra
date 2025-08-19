# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.
# pylint: disable-msg=E1101

from typing import Any

from xpra.util.env import envbool
from xpra.os_util import gi_import
from xpra.net.common import Packet
from xpra.platform.pointer import get_pointer_device
from xpra.server.subsystem.stub import StubServerMixin
from xpra.log import Logger

log = Logger("pointer")

GLib = gi_import("GLib")

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
        self.pointer_device_map: dict = {}
        self.pointer_device = None
        self.touchpad_device = None

    def init(self, opts) -> None:
        self.input_devices = opts.input_devices

    def setup(self) -> None:
        self.pointer_device = get_pointer_device()
        if not self.pointer_device:
            log.warn("Warning: no pointer device available, using NoPointerDevice")
            from xpra.pointer.nopointer import NoPointerDevice
            self.pointer_device = NoPointerDevice()
        log("pointer_device=%s", self.pointer_device)

    def init_virtual_devices(self, devices: dict[str, Any]) -> None:
        # pylint: disable=import-outside-toplevel
        # (this runs in the main thread - before the main loop starts)
        # for the time being, we only use the pointer if there is one:
        if not hasattr(self, "get_display_size"):
            log.warn("cannot enable virtual devices without a display")
            return
        pointer = devices.get("pointer")
        touchpad = devices.get("touchpad")
        log("init_virtual_devices(%s) got pointer=%s, touchpad=%s", devices, pointer, touchpad)
        self.input_devices = "xtest"
        if pointer:
            uinput_device = pointer.get("uinput")
            device_path = pointer.get("device")
            if uinput_device:
                from xpra.x11.uinput.device import UInputPointerDevice
                self.input_devices = "uinput"
                self.pointer_device = UInputPointerDevice(uinput_device, device_path)
                self.verify_uinput_pointer_device()
        if self.input_devices == "uinput" and touchpad:
            uinput_device = touchpad.get("uinput")
            device_path = touchpad.get("device")
            if uinput_device:
                from xpra.x11.uinput.device import UInputTouchpadDevice
                root_w, root_h = self.get_display_size()
                self.touchpad_device = UInputTouchpadDevice(uinput_device, device_path, root_w, root_h)
        try:
            log.info("pointer device emulation using %s", str(self.pointer_device).replace("PointerDevice", ""))
        except Exception as e:
            log("cannot get pointer device class from %s: %s", self.pointer_device, e)

    def verify_uinput_pointer_device(self) -> None:
        from xpra.x11.server.xtest_pointer import XTestPointerDevice
        xtest = XTestPointerDevice()
        ox, oy = 100, 100
        from xpra.x11.error import xlog, xswallow
        with xlog:
            xtest.move_pointer(ox, oy, {})
        nx, ny = 200, 200
        self.pointer_device.move_pointer(nx, ny, {})

        def verify_uinput_moved() -> None:
            pos = (ox, oy)
            with xswallow:
                from xpra.x11.bindings.keyboard import X11KeyboardBindings
                pos = X11KeyboardBindings().query_pointer()
                log("X11Keyboard.query_pointer=%s", pos)
            if pos == (ox, oy):
                log.warn("Warning: %s failed verification", self.pointer_device)
                log.warn(" expected pointer at %s, now at %s", (nx, ny), pos)
                log.warn(" using XTest fallback")
                self.pointer_device = xtest
                self.input_devices = "xtest"

        GLib.timeout_add(1000, verify_uinput_moved)

    # TODO: use "screen-size-changed" signal instead:
    def configure_best_screen_size(self) -> tuple[int, int]:
        root_w, root_h = super().configure_best_screen_size()
        if self.touchpad_device:
            self.touchpad_device.root_w = root_w
            self.touchpad_device.root_h = root_h
        return root_w, root_h

    def get_caps(self, source) -> dict[str, Any]:
        caps: dict[str, Any] = {}
        if "features" in source.wants:
            caps = {
                "wheel.precise": self.pointer_device.has_precise_wheel(),
                "pointer.optional": True,
                "touchpad-device": bool(self.touchpad_device),
            }
        return caps

    def get_server_features(self, _source=None) -> dict[str, Any]:
        return {
            "input-devices": self.input_devices,
            "pointer.relative": True,  # assumed available in 5.0.3
        }

    def _move_pointer(self, device_id: int, wid: int, pos, *args) -> None:
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
                            log(
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
        log("process_pointer_button(%s, %s)", proto, packet)
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
            #    log(f"dropped outdated sequence {seq}, latest is {highest_seq}")
            #    return
            self.pointer_sequence[device_id] = seq
        self.do_process_button_action(proto, device_id, wid, button, pressed, pointer, props)

    def _process_button_action(self, proto, packet: Packet) -> None:
        log("process_button_action(%s, %s)", proto, packet)
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
        props: dict[str, Any] = {
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
        log("_process_pointer(%s, %s) readonly=%s, ui_driver=%s",
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
                log(f"dropped outdated sequence {seq}, latest is {highest_seq}")
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
        log("_process_pointer_position(%s, %s) readonly=%s, ui_driver=%s",
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
        log("client %s input devices:", self.input_devices_format)
        print_nested_dict(self.input_devices_data, print_fn=log)
        self.setup_input_devices()

    def setup_input_devices(self) -> None:
        from xpra.server import features
        log("setup_input_devices() input_devices feature=%s", features.pointer)
        from xpra.util.system import is_X11
        if not is_X11():
            return
        if not features.pointer:
            return
        xinputlog = Logger("xinput", "pointer")
        xinputlog("setup_input_devices() format=%s, input_devices=%s", self.input_devices_format, self.input_devices)
        xinputlog("setup_input_devices() input_devices_data=%s", self.input_devices_data)
        # xinputlog("setup_input_devices() input_devices_data=%s", self.input_devices_data)
        xinputlog("setup_input_devices() pointer device=%s", self.pointer_device)
        xinputlog("setup_input_devices() touchpad device=%s", self.touchpad_device)
        self.pointer_device_map = {}
        if not self.touchpad_device:
            # no need to assign anything, we only have one device anyway
            return
        # if we find any absolute pointer devices,
        # map them to the "touchpad_device"
        XIModeAbsolute = 1
        for deviceid, device_data in self.input_devices_data.items():
            name = device_data.get("name")
            # xinputlog("[%i]=%s", deviceid, device_data)
            xinputlog("[%i]=%s", deviceid, name)
            if device_data.get("use") != "slave pointer":
                continue
            classes = device_data.get("classes")
            if not classes:
                continue
            # look for absolute pointer devices:
            touchpad_axes = []
            for i, defs in classes.items():
                xinputlog(" [%i]=%s", i, defs)
                mode = defs.get("mode")
                label = defs.get("label")
                if not mode or mode != XIModeAbsolute:
                    continue
                if defs.get("min", -1) == 0 and defs.get("max", -1) == (2 ** 24 - 1):
                    touchpad_axes.append((i, label))
            if len(touchpad_axes) == 2:
                xinputlog.info("found touchpad device: %s", name)
                xinputlog("axes: %s", touchpad_axes)
                self.pointer_device_map[deviceid] = self.touchpad_device

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
