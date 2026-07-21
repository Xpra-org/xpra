# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.
# pylint: disable-msg=E1101

from time import monotonic
from typing import Any
from collections.abc import Sequence

from xpra.server.source.pointer import PointerConnection
from xpra.util.env import envbool, envint
from xpra.util.objects import typedict
from xpra.net.common import Packet, PacketElement, BACKWARDS_COMPATIBLE
from xpra.server.subsystem.stub import StubSubsystem
from xpra.log import Logger

log = Logger("pointer")

INPUT_SEQ_NO = envbool("XPRA_INPUT_SEQ_NO", False)
ALWAYS_NOTIFY_MOTION = envbool("XPRA_ALWAYS_NOTIFY_MOTION", False)

# Drag-as-scroll heuristic: when button-1 is held on a window and the pointer
# moves vertically, treat the motion as a scroll event for downstream consumers
# (chiefly image filters that want temporal stability across scrolls, beyond
# wheel events).  Two complementary signals are used to separate scrollbar-thumb drags
# from text-selection and other button-1 drags:
#   (a) press-X close to the right edge of the window (scrollbar zone), and
#   (b) the drag motion remains near-vertical (low |dx|:|dy| ratio).
# (a) is the strong signal when window geometry is available.  (b) is the
# fallback when geometry can't be resolved.  Either signal classifying the
# drag as 'not a scrollbar drag' suppresses emits for the rest of that drag.
#
#   XPRA_DRAG_SCROLL_ENABLED                  master switch
#   XPRA_DRAG_SCROLL_MIN_DY_PX                cumulative |dy| (px) before emit
#   XPRA_DRAG_SCROLL_EMIT_INTERVAL_MS         minimum gap between emits per drag
#   XPRA_DRAG_SCROLLBAR_ZONE_PX               width (px) of the right-edge zone
#                                             treated as the scrollbar (~chromium
#                                             default scrollbar width + margin)
#   XPRA_DRAG_SCROLL_SELECTION_PROBE_DY_PX    accumulated |dy| at which the dx/dy
#                                             ratio is first evaluated; below this
#                                             motion is considered too short to
#                                             classify reliably
#   XPRA_DRAG_SCROLL_SELECTION_DX_PCT         % of |dy| that |dx| may reach before
#                                             the drag is latched as selection-like
#                                             (only consulted when zone is unknown)
DRAG_SCROLL_ENABLED = envbool("XPRA_DRAG_SCROLL_ENABLED", False)
DRAG_SCROLL_MIN_DY_PX = envint("XPRA_DRAG_SCROLL_MIN_DY_PX", 4)
DRAG_SCROLL_EMIT_INTERVAL_MS = envint("XPRA_DRAG_SCROLL_EMIT_INTERVAL_MS", 50)
DRAG_SCROLLBAR_ZONE_PX = envint("XPRA_DRAG_SCROLLBAR_ZONE_PX", 20)
DRAG_SCROLL_SELECTION_PROBE_DY_PX = envint("XPRA_DRAG_SCROLL_SELECTION_PROBE_DY_PX", 6)
DRAG_SCROLL_SELECTION_DX_PCT = envint("XPRA_DRAG_SCROLL_SELECTION_DX_PCT", 40)


class PointerManager(StubSubsystem):
    """
    Mixin for servers that handle pointer devices
    (mouse, etc)
    """
    __slots__ = (
        "_button1_drag", "double_click_distance", "double_click_time", "input_devices",
        "input_devices_data", "last_mouse_user", "pointer_device", "pointer_device_map",
        "pointer_sequence", "touchpad_device",
    )
    PREFIX = "pointer"

    def __init__(self, server=None):
        StubSubsystem.__init__(self, server)
        self.input_devices = "auto"
        self.input_devices_data = {}
        self.pointer_sequence = {}
        self.last_mouse_user = ""
        self.pointer_device_map: dict = {}
        self.pointer_device = None
        self.touchpad_device = None
        self.double_click_time = -1
        self.double_click_distance = -1, -1
        # Per-window state for the drag-as-scroll heuristic.
        # Keyed by wid (not device_id) because legacy v4 protocol paths use
        # different device_id defaults for press (0) vs motion (-1), which
        # would otherwise miss every drag.  Each entry:
        #   {"last_x": int, "last_y": int,
        #    "accum_dx_abs": int, "accum_dy_abs": int,
        #    "in_scrollbar_zone": bool|None,    # None = window geom unknown
        #    "looks_like_selection": bool,      # latched once True
        #    "last_emit_t_ms": float}
        # Populated on button-1 press, consumed on motion, cleared on release.
        self._button1_drag: dict[int, dict] = {}

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

    def get_pointer_position(self) -> tuple[int, int]:
        from xpra.platform.pointer import get_position
        try:
            return get_position()
        except NotImplementedError:
            return 0, 0

    def get_info(self, _proto) -> dict[str, Any]:
        info = {
            "double-click": {
                "time": self.double_click_time,
                "distance": self.double_click_distance,
            },
        }
        return {PointerManager.PREFIX: info}

    def add_new_client(self, ss, c: typedict) -> None:
        from xpra.server.source.pointer import PointerConnection
        pointer_clients = self.get_sources_by_type(PointerConnection, ss)
        if pointer_clients:
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
        display = self.get_subsystem("display")
        if display is None:
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
                root_w, root_h = display.get_display_size()
                self.touchpad_device = UInputTouchpadDevice(uinput_device, device_path, root_w, root_h)
                # `display-geometry-changed` is a subsystem-local signal
                # owned by `DisplayManager` (via `SignalEmitter`):
                if display := self.get_subsystem("display"):
                    display.connect("display-geometry-changed", self.update_touchpad_size)
        if self.pointer_device:
            try:
                log.info("pointer device emulation using %r", str(self.pointer_device).replace("PointerDevice", ""))
            except Exception as e:
                log("cannot get pointer device class from %s: %s", self.pointer_device, e)

    def update_touchpad_size(self, *_args) -> None:
        if td := self.touchpad_device:
            # the DisplayManager subsystem is what emits this signal:
            display = self.get_subsystem("display")
            if display is None:
                return
            root_w, root_h = display.get_display_size()
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

        self.timeout_add(1000, verify_uinput_moved)

    def get_server_features(self, _source=None) -> dict[str, Any]:
        return {
            "input-devices": self.input_devices,
            "pointer.relative": True,  # assumed available in 5.0.3
            "pointer.optional": True,
            "wheel.precise": self.pointer_device.has_precise_wheel(),
            "touchpad-device": bool(self.touchpad_device),
        }

    def _adjust_pointer(self, proto, device_id, wid: int, pointer):
        # the window may not be mapped at the same location by the client:
        ss = self.get_server_source(proto)
        if not hasattr(ss, "update_mouse"):
            return pointer
        window_sub = self.get_subsystem("window")
        if window_sub is None:
            return pointer
        window = window_sub.get_window(wid)
        if ss and window:
            ws = ss.get_window_source(wid)
            if ws:
                mapped_at = ws.mapped_at
                pos = window_sub.get_window_position(window)
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
            seq = self.pointer_sequence.get(device_id, 0)
            self.may_record_pointer_event("pointer-motion", device_id, seq, wid, pointer, props or {})
            return pointer
        return None

    def may_record_pointer_event(self, packet_type: str, *data: PacketElement) -> None:
        pointer_sources = self.get_sources_by_type(PointerConnection)
        for ss in pointer_sources:
            if ss.pointer_record:
                ss.send_async(packet_type, *data)

    def _process_pointer_button(self, proto, packet: Packet) -> None:
        log("process_pointer_button(%s, %s)", proto, packet)
        if self.is_readonly(proto):
            return
        ss = self.get_server_source(proto)
        if not hasattr(ss, "update_mouse"):
            return
        ss.user_event("pointer-button")
        self.last_mouse_user = ss.uuid
        self.server.set_ui_driver(ss)
        device_id = packet.get_i64(1)
        seq = packet.get_u64(2)
        wid = packet.get_wid(3)
        button = packet.get_u8(4)
        pressed = packet.get_bool(5)
        pointer = packet.get_ints(6) if BACKWARDS_COMPATIBLE else packet.get_u16s(6)
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
        if self.is_readonly(proto):
            return
        ss = self.get_server_source(proto)
        if not hasattr(ss, "update_mouse"):
            return
        ss.user_event("button-action")
        self.last_mouse_user = ss.uuid
        self.server.set_ui_driver(ss)
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
        window_sub = self.get_subsystem("window")
        if window_sub is None:
            return
        wid = window_sub.get_wid(model)
        if not wid:
            return
        pointer_sources = self.get_sources_by_type(PointerConnection)
        for ss in pointer_sources:
            if ALWAYS_NOTIFY_MOTION or self.last_mouse_user is None or self.last_mouse_user != ss.uuid:
                ss.update_mouse(wid, event.x_root, event.y_root, event.x, event.y)

    def get_pointer_device(self, deviceid: int):
        # log("get_pointer_device(%i) input_devices_data=%s", deviceid, self.input_devices_data)
        if self.input_devices_data:
            if device_data := self.input_devices_data.get(deviceid):
                log("get_pointer_device(%i) device=%s", deviceid, device_data.get("name"))
        device = self.pointer_device_map.get(deviceid) or self.pointer_device
        return device

    @staticmethod
    def get_pointer_window_position(pos, props=None) -> tuple[int, int] | None:
        """Return window-relative coordinates from properties or a legacy tuple."""
        relative = (props or {}).get("window-position")
        if isinstance(relative, (tuple, list)) and len(relative) == 2:
            try:
                return int(relative[0]), int(relative[1])
            except (TypeError, ValueError):
                pass
        if len(pos) >= 4:
            return int(pos[2]), int(pos[3])
        return None

    def _get_pointer_abs_coordinates(self, wid: int, pos, props=None) -> tuple[int, int]:
        # simple absolute coordinates
        x, y = pos[:2]
        relative = self.get_pointer_window_position(pos, props)
        if relative:
            window_sub = self.get_subsystem("window")
            if window_sub is not None:
                # relative coordinates
                if model := window_sub.get_window(wid):
                    rx, ry = relative
                    geom = model.get_geometry()
                    x = geom[0] + rx
                    y = geom[1] + ry
                    log("_get_pointer_abs_coordinates(%i, %s)=%s window geometry=%s", wid, pos, (x, y), geom)
        return x, y

    def get_pointer_target(self, proto, wid: int, pos, props=None) -> tuple[int, int]:
        return self._get_pointer_abs_coordinates(wid, pos, props)

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
        if self.is_readonly(proto):
            return False
        pos = self.get_pointer_device(device_id).get_position()
        target = self.get_pointer_target(proto, wid, pointer, props)
        if (pointer and pos != target) or self.input_devices == "xi":
            self._move_pointer(device_id, wid, target, props)
        return True

    def _update_modifiers(self, proto, wid: int, modifiers: Sequence[str]) -> None:
        if self.is_readonly(proto):
            return
        if ss := self.get_server_source(proto):
            if self.server.ui_driver and self.server.ui_driver != ss.uuid:
                return
            if hasattr(ss, "keyboard_config"):
                modifiers = [x for x in modifiers if x]
                ss.make_keymask_match(modifiers)
            window_sub = self.get_subsystem("window")
            if window_sub is not None and wid == window_sub.get_focus():
                ss.user_event("focus-changed")

    def do_process_button_action(self, proto, device_id: int, wid: int, button: int, pressed: bool,
                                 pointer, props: dict) -> None:
        if "modifiers" in props:
            self._update_modifiers(proto, wid, props.get("modifiers", ()))
        if DRAG_SCROLL_ENABLED and button == 1 and wid:
            if pressed:
                self._button1_drag[wid] = self._make_button1_drag_state(wid, pointer, props)
            else:
                self._button1_drag.pop(wid, None)
        pointer_props = {
            key: props[key] for key in ("window-position", "monitor") if key in props
        }
        if self.process_mouse_common(proto, device_id, wid, pointer, pointer_props):
            seq = self.pointer_sequence.get(device_id, 0)
            self.may_record_pointer_event("pointer-button", device_id, seq, wid, button, pressed, pointer, {})
            self.button_action(device_id, wid, button, pressed, {})

    def _make_button1_drag_state(self, wid: int, pointer, props=None) -> dict:
        """Snapshot the button-1 press for the drag-as-scroll heuristic.

        Computes whether the press landed inside the window's right-edge
        scrollbar zone, using the window-relative position property and the
        window's geometry width when reachable. Stores press coordinates so
        the motion handler can accumulate dx/dy.
        """
        try:
            press_x = int(pointer[0]) if pointer and len(pointer) >= 1 else 0
            press_y = int(pointer[1]) if pointer and len(pointer) >= 2 else 0
        except (TypeError, ValueError):
            press_x, press_y = 0, 0
        in_zone: bool | None = None
        rel_x: int | None = None
        if relative := self.get_pointer_window_position(pointer, props):
            rel_x = relative[0]
        window_width = self._lookup_window_width(wid)
        if rel_x is not None and window_width:
            in_zone = (window_width - rel_x) <= DRAG_SCROLLBAR_ZONE_PX
        return {
            "last_x": press_x,
            "last_y": press_y,
            "accum_dx_abs": 0,
            "accum_dy_abs": 0,
            "in_scrollbar_zone": in_zone,
            "looks_like_selection": False,
            "last_emit_t_ms": 0.0,
        }

    def _lookup_window_width(self, wid: int) -> int | None:
        """Return the width of the window with id ``wid``, or ``None``.

        Mirrors the geometry lookup in :meth:`_get_pointer_abs_coordinates`:
        only works when this mixin is composed with :class:`WindowServer`
        (i.e. on the X11 server) and the window model is reachable.
        """
        if not (ws := self.get_subsystem("window")):
            return None
        if not (model := ws.get_window(wid)):
            return None
        geom = model.get_geometry()
        if not geom or len(geom) < 4:
            return None
        return int(geom[2])

    def _maybe_record_drag_scroll(self, wid: int, pdata: Sequence[int]) -> None:
        """Treat sustained button-1 + near-vertical motion as a scroll event.

        Distinguishes scrollbar-thumb drags from text-selection drags using
        two complementary signals: (a) press inside the window's right-edge
        scrollbar zone (strong, used when window geometry is reachable) and
        (b) accumulated |dx| vs |dy| ratio (fallback, used when geometry is
        unknown or as additional confidence).  A drag classified as anything
        other than a scrollbar drag has emits suppressed for its remaining
        lifetime.

        Keyed on ``wid`` (not ``device_id``) because the legacy v4 protocol
        paths used by the bundled HTML5 client deliver press with
        ``device_id=0`` and motion with ``device_id=-1``; keying on wid
        sidesteps that mismatch.  Otherwise rate-limited per drag via
        ``DRAG_SCROLL_MIN_DY_PX`` and ``DRAG_SCROLL_EMIT_INTERVAL_MS``.
        """
        if not DRAG_SCROLL_ENABLED or not wid:
            return
        drag = self._button1_drag.get(wid)
        if not drag or len(pdata) < 2:
            return
        try:
            cur_x = int(pdata[0])
            cur_y = int(pdata[1])
        except (TypeError, ValueError):
            return
        drag["accum_dx_abs"] += abs(cur_x - drag["last_x"])
        drag["accum_dy_abs"] += abs(cur_y - drag["last_y"])
        drag["last_x"] = cur_x
        drag["last_y"] = cur_y
        # Strong reject: press was clearly not on the scrollbar.
        if drag["in_scrollbar_zone"] is False:
            return
        # Fallback signal (only when zone is unknown): motion-direction.
        # Once the ratio crosses the threshold we latch the drag as
        # selection-like so a later returns-to-vertical micro-movement
        # doesn't reopen the emit gate.
        if drag["in_scrollbar_zone"] is None and not drag["looks_like_selection"]:
            if drag["accum_dy_abs"] >= DRAG_SCROLL_SELECTION_PROBE_DY_PX and drag["accum_dx_abs"] * 100 >= DRAG_SCROLL_SELECTION_DX_PCT * drag["accum_dy_abs"]:
                drag["looks_like_selection"] = True
                log("drag-as-scroll: wid=%i classified as selection-like (unknown zone, dx=%i dy=%i)",
                    wid, drag["accum_dx_abs"], drag["accum_dy_abs"])
        if drag["looks_like_selection"]:
            return
        # Pixel threshold + rate limit.
        if drag["accum_dy_abs"] < DRAG_SCROLL_MIN_DY_PX:
            return
        now_ms = monotonic() * 1000.0
        if (now_ms - drag["last_emit_t_ms"]) < DRAG_SCROLL_EMIT_INTERVAL_MS:
            return
        drag["last_emit_t_ms"] = now_ms
        drag["accum_dx_abs"] = 0
        drag["accum_dy_abs"] = 0
        log("drag-as-scroll: wid=%i y=%i zone=%s",
            wid, cur_y, drag["in_scrollbar_zone"])
        for ss in self.window_sources():
            ss.record_scroll_event(wid)

    def button_action(self, device_id: int, wid: int, button: int, pressed: bool, props: dict) -> None:
        device = self.get_pointer_device(device_id)
        assert device, "pointer device %s not found" % device_id
        if button in (4, 5) and wid:
            self.record_wheel_event(wid, button)
        log("%s%s", device.click, (button, pressed, props))
        device.click(button, pressed, props)

    def _process_pointer_motion(self, proto, packet: Packet) -> None:
        # v5 packet format
        log("_process_pointer_motion(%s, %s) readonly=%s, ui_driver=%s",
            proto, packet, self.is_readonly(proto), self.server.ui_driver)
        if self.is_readonly(proto):
            return
        ss = self.get_server_source(proto)
        if not hasattr(ss, "update_mouse"):
            return
        device_id = packet.get_i64(1)
        seq = packet.get_u64(2)
        wid = packet.get_wid(3)
        pdata = packet.get_ints(4) if BACKWARDS_COMPATIBLE else packet.get_u16s(4)
        props = packet.get_dict(5)
        if device_id >= 0:
            highest_seq = self.pointer_sequence.get(device_id, 0)
            if INPUT_SEQ_NO and 0 <= seq <= highest_seq:
                log(f"dropped outdated sequence {seq}, latest is {highest_seq}")
                return
            self.pointer_sequence[device_id] = seq
        pointer = pdata[:2]
        ss.mouse_last_relative_position = self.get_pointer_window_position(pdata, props) or (-1, -1)
        ss.mouse_last_position = pointer
        if self.server.ui_driver and self.server.ui_driver != ss.uuid:
            return
        ss.user_event("pointer")
        self.last_mouse_user = ss.uuid
        if self.process_mouse_common(proto, device_id, wid, pdata, props):
            modifiers = props.get("modifiers")
            if modifiers is not None:
                self._update_modifiers(proto, wid, modifiers)
        self._maybe_record_drag_scroll(wid, pdata)

    def _process_pointer_position(self, proto, packet: Packet) -> None:
        log("_process_pointer_position(%s, %s) readonly=%s, ui_driver=%s",
            proto, packet, self.is_readonly(proto), self.server.ui_driver)
        if self.is_readonly(proto):
            return
        ss = self.get_server_source(proto)
        if not hasattr(ss, "update_mouse"):
            return
        wid = packet.get_wid()
        pdata = packet.get_ints(2)
        modifiers = packet.get_strs(3)
        pointer = pdata[:2]
        ss.mouse_last_relative_position = pdata[2:4] if len(pdata) >= 4 else (-1, -1)
        ss.mouse_last_position = pointer
        if self.server.ui_driver and self.server.ui_driver != ss.uuid:
            return
        ss.user_event("pointer-position")
        self.last_mouse_user = ss.uuid
        # the legacy "pointer-position" packet carries no per-device id and no
        # usable props (those only reach us via the v5 "pointer-motion" packet);
        # any trailing elements from older clients are ignored:
        props: dict[str, Any] = {}
        device_id = -1
        if self.process_mouse_common(proto, device_id, wid, pdata, props):
            self._update_modifiers(proto, wid, modifiers)
        self._maybe_record_drag_scroll(wid, pdata)

    def _process_pointer_wheel(self, proto, packet: Packet) -> None:
        assert self.pointer_device.has_precise_wheel()
        if self.is_readonly(proto):
            return
        ss = self.get_server_source(proto)
        if not ss:
            return
        wid = packet.get_wid()
        button = packet.get_u8(2)
        distance = packet.get_i64(3)
        pointer = packet.get_ints(4) if BACKWARDS_COMPATIBLE else packet.get_u16s(4)
        modifiers = packet.get_strs(5)
        # buttons = packet.get_ints(6)
        device_id = -1
        props = packet.get_dict(7) if len(packet) >= 8 and isinstance(packet[7], dict) else {}
        self.record_wheel_event(wid, button)
        if self.do_process_mouse_common(proto, device_id, wid, pointer, props):
            self.last_mouse_user = ss.uuid
            self._update_modifiers(proto, wid, modifiers)
            self.may_record_pointer_event("pointer-wheel", wid, button, distance, tuple(pointer), tuple(modifiers))
            self.pointer_device.wheel_motion(button, distance / 1000.0)  # pylint: disable=no-member

    def record_wheel_event(self, wid: int, button: int) -> None:
        """ this may be used as a compression hint """
        log("recording scroll event for button %i", button)
        window_sub = self.get_subsystem("window")
        if window_sub is None:
            return
        for ss in window_sub.window_sources():
            ss.record_scroll_event(wid)

    def init_packet_handlers(self) -> None:
        if BACKWARDS_COMPATIBLE:
            self.add_packets("pointer-position", main_thread=True)  # pre v5
            self.add_legacy_alias("wheel-motion", "pointer-wheel")
            self.add_legacy_alias("pointer", "pointer-motion")
            self.add_packet_handler("button-action", self._process_button_action, True)  # pre v5
        self.add_packets(
            "pointer-button",
            "pointer-motion",
            "pointer-wheel",
            main_thread=True
        )
