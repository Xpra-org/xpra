# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.
# pylint: disable-msg=E1101

from typing import Any

from xpra.util.env import envbool
from xpra.util.objects import typedict
from xpra.os_util import gi_import
from xpra.net.common import Packet
from xpra.server.subsystem.stub import StubServerMixin
from xpra.log import Logger

log = Logger("pointer")

GLib = gi_import("GLib")

INPUT_SEQ_NO = envbool("XPRA_INPUT_SEQ_NO", False)
ALWAYS_NOTIFY_MOTION = envbool("XPRA_ALWAYS_NOTIFY_MOTION", False)


class PointerServer(StubServerMixin):
    """
    Mixin for servers that handle pointer devices
    (mouse, etc)
    """
    PREFIX = "pointer"

    def __init__(self):
        StubServerMixin.__init__(self)
        self.input_devices = "auto"
        self.input_devices_data = {}
        self.pointer_sequence = {}
        self.last_mouse_user = ""
        self.pointer_device_map: dict = {}
        self.pointer_device = None
        self.touchpad_device = None
        self.double_click_time = -1
        self.double_click_distance = -1, -1
        # duplicated:
        self.readonly = False

    def init(self, opts) -> None:
        self.input_devices = opts.input_devices

    def setup(self) -> None:
        self.pointer_device = self.make_pointer_device()
        if not self.pointer_device:
            log.warn("Warning: no pointer device available, using NoPointerDevice")
            from xpra.pointer.nopointer import NoPointerDevice
            self.pointer_device = NoPointerDevice()
        log("pointer_device=%s", self.pointer_device)

    def make_pointer_device(self):
        from xpra.platform.pointer import get_pointer_device
        return get_pointer_device()

    def get_info(self, _proto) -> dict[str, Any]:
        info = {
            "double-click": {
                "time": self.double_click_time,
                "distance": self.double_click_distance,
            },
        }
        return {PointerServer.PREFIX: info}

    def add_new_client(self, ss, c: typedict, send_ui: bool, share_count: int) -> None:
        if share_count > 0:
            self.double_click_time = -1
            self.double_click_distance = -1, -1
        else:
            self.double_click_time = c.intget("double_click.time", -1)
            self.double_click_distance = c.intpair("double_click.distance", (-1, -1))
        log("double-click time=%s, distance=%s", self.double_click_time, self.double_click_distance)

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
                # this signal should always be defined,
                # since I can't imagine how we can have a touchpad device without a display!
                if "display-geometry-changed" in self.__signals__:
                    self.connect("display-geometry-changed", self.update_touchpad_size)
        if self.pointer_device:
            try:
                log.info("pointer device emulation using %r", str(self.pointer_device).replace("PointerDevice", ""))
            except Exception as e:
                log("cannot get pointer device class from %s: %s", self.pointer_device, e)

    def update_touchpad_size(self) -> None:
        td = self.touchpad_device
        if td:
            # this handler only runs when the DisplayManager emits the signal,
            # so we can assume that the `get_display_size()` method is available:
            root_w, root_h = self.get_display_size()
            td.root_w = root_w
            td.root_h = root_h

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
                from xpra.x11.bindings.core import X11CoreBindings
                pos = X11CoreBindings().query_pointer()
                log("X11Keyboard.query_pointer=%s", pos)
            if pos == (ox, oy):
                log.warn("Warning: %s failed verification", self.pointer_device)
                log.warn(" expected pointer at %s, now at %s", (nx, ny), pos)
                log.warn(" using XTest fallback")
                self.pointer_device = xtest
                self.input_devices = "xtest"

        GLib.timeout_add(1000, verify_uinput_moved)

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

    def _process_pointer_button(self, proto, packet: Packet) -> None:
        log("process_pointer_button(%s, %s)", proto, packet)
        if self.readonly:
            return
        ss = self.get_server_source(proto)
        if not hasattr(ss, "update_mouse"):
            return
        ss.emit("user-event", "pointer-button")
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
        ss.emit("user-event", "button-action")
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

    def _motion_signaled(self, model, event) -> None:
        log("motion_signaled(%s, %s) last mouse user=%s", model, event, self.last_mouse_user)
        # find the window model for this gdk window:
        wid = self._window_to_id.get(model)
        if not wid:
            return
        for ss in self._server_sources.values():
            if ALWAYS_NOTIFY_MOTION or self.last_mouse_user is None or self.last_mouse_user != ss.uuid:
                if hasattr(ss, "update_mouse"):
                    ss.update_mouse(wid, event.x_root, event.y_root, event.x, event.y)

    def get_pointer_device(self, deviceid: int):
        # log("get_pointer_device(%i) input_devices_data=%s", deviceid, self.input_devices_data)
        if self.input_devices_data:
            device_data = self.input_devices_data.get(deviceid)
            if device_data:
                log("get_pointer_device(%i) device=%s", deviceid, device_data.get("name"))
        device = self.pointer_device_map.get(deviceid) or self.pointer_device
        return device

    def _get_pointer_abs_coordinates(self, wid: int, pos) -> tuple[int, int]:
        # simple absolute coordinates
        x, y = pos[:2]
        from xpra.server.subsystem.window import WindowServer
        if len(pos) >= 4 and isinstance(self, WindowServer):
            # relative coordinates
            model = self._id_to_window.get(wid)
            if model:
                rx, ry = pos[2:4]
                geom = model.get_geometry()
                x = geom[0] + rx
                y = geom[1] + ry
                log("_get_pointer_abs_coordinates(%i, %s)=%s window geometry=%s", wid, pos, (x, y), geom)
        return x, y

    def _move_pointer(self, device_id: int, wid: int, pos, props=None) -> None:
        # (this is called within a `xswallow` context)
        x, y = self._get_pointer_abs_coordinates(wid, pos)
        self.device_move_pointer(device_id, wid, (x, y), props or {})

    def device_move_pointer(self, device_id: int, wid: int, pos, props: dict):
        device = self.get_pointer_device(device_id)
        x, y = pos
        log("move_pointer(%s, %s, %s) device=%s, position=%s", wid, pos, device_id, device, (x, y))
        try:
            device.move_pointer(x, y, props)
        except Exception as e:
            log.error("Error: failed to move the pointer to %sx%s using %s", x, y, device)
            log.estr(e)

    def do_process_mouse_common(self, proto, device_id: int, wid: int, pointer, props) -> bool:
        log("do_process_mouse_common%s", (proto, device_id, wid, pointer, props))
        if self.readonly:
            return False
        pos = self.get_pointer_device(device_id).get_position()
        if (pointer and pos != pointer[:2]) or self.input_devices == "xi":
            self._move_pointer(device_id, wid, pointer, props)
        return True

    def _update_modifiers(self, proto, wid: int, modifiers) -> None:
        if self.readonly:
            return
        ss = self.get_server_source(proto)
        if ss:
            if self.ui_driver and self.ui_driver != ss.uuid:
                return
            if hasattr(ss, "keyboard_config"):
                ss.make_keymask_match(modifiers)
            if wid == self.get_focus():
                ss.emit("user-event", "focus-changed")

    def do_process_button_action(self, proto, device_id: int, wid: int, button: int, pressed: bool,
                                 pointer, props: dict) -> None:
        if "modifiers" in props:
            self._update_modifiers(proto, wid, props.get("modifiers"))
        props = {}
        if self.process_mouse_common(proto, device_id, wid, pointer, props):
            self.button_action(device_id, wid, pointer, button, pressed, props)

    def button_action(self, device_id: int, wid: int, pointer: tuple, button: int, pressed: bool, props: dict) -> None:
        device = self.get_pointer_device(device_id)
        assert device, "pointer device %s not found" % device_id
        if button in (4, 5) and wid:
            self.record_wheel_event(wid, button)
        log("%s%s", device.click, (button, pressed, props))
        device.click(pointer, button, pressed, props)

    def _process_pointer(self, proto, packet: Packet) -> None:
        # v5 packet format
        log("_process_pointer(%s, %s) readonly=%s, ui_driver=%s", proto, packet, self.readonly, self.ui_driver)
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
        ss.emit("user-event", "pointer")
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
        ss.emit("user-event", "pointer-position")
        self.last_mouse_user = ss.uuid
        props: dict[str, Any] = {}
        device_id = -1
        if len(packet) >= 6:
            device_id = packet[5]
        if self.process_mouse_common(proto, device_id, wid, pdata, props):
            self._update_modifiers(proto, wid, modifiers)

    def _process_wheel_motion(self, proto, packet: Packet) -> None:
        assert self.pointer_device.has_precise_wheel()
        ss = self.get_server_source(proto)
        if not ss:
            return
        wid = packet.get_wid()
        button = packet.get_u8(2)
        distance = packet.get_i64(3)
        pointer = packet.get_ints(4)
        modifiers = packet.get_strs(5)
        # _buttons = packet[6]
        device_id = -1
        props = {}
        self.record_wheel_event(wid, button)
        if self.do_process_mouse_common(proto, device_id, wid, pointer, props):
            self.last_mouse_user = ss.uuid
            self._update_modifiers(proto, wid, modifiers)
            self.pointer_device.wheel_motion(button, distance / 1000.0)  # pylint: disable=no-member

    def record_wheel_event(self, wid: int, button: int) -> None:
        log("recording scroll event for button %i", button)
        for ss in self.window_sources():
            ss.record_scroll_event(wid)

    def init_packet_handlers(self) -> None:
        self.add_packets(
            # mouse:
            "pointer-button", "pointer",
            "pointer-position",  # pre v5
            "wheel-motion",
            main_thread=True
        )
        self.add_packet_handler("button-action", self._process_button_action, True)  # pre v5
