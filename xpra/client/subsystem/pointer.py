# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import math
from typing import Any
from time import monotonic
from collections.abc import Sequence

from xpra.os_util import OSX
from xpra.client.base.stub import StubClientSubsystem
from xpra.net.common import Packet, PacketElement, BACKWARDS_COMPATIBLE
from xpra.net.packet_type import POINTER_MOTION, POINTER_BUTTON, POINTER_WHEEL
from xpra.util.objects import typedict
from xpra.util.env import envbool, envint
from xpra.util.parsing import is_sharing_sync, FALSE_OPTIONS
from xpra.log import Logger

log = Logger("pointer")

MOUSE_DELAY = envint("XPRA_MOUSE_DELAY", 0)
MOUSE_DELAY_AUTO = envbool("XPRA_MOUSE_DELAY_AUTO", True)
SKIP_DUPLICATE_BUTTON_EVENTS: bool = envbool("XPRA_SKIP_DUPLICATE_BUTTON_EVENTS", True)

SMOOTH_SCROLL: bool = envbool("XPRA_SMOOTH_SCROLL", True)
MOUSE_SCROLL_SQRT_SCALE: bool = envbool("XPRA_MOUSE_SCROLL_SQRT_SCALE", OSX)
MOUSE_SCROLL_MULTIPLIER: int = envint("XPRA_MOUSE_SCROLL_MULTIPLIER", 100)


def get_double_click_caps() -> dict[str, Any]:
    from xpra.platform.gui import get_double_click_time, get_double_click_distance
    return {
        "time": get_double_click_time(),
        "distance": get_double_click_distance(),
    }


def parse_mousewheel(mousewheel: str) -> tuple[bool, dict]:
    mw = (mousewheel or "").lower().replace("-", "").split(",")
    wheel_smooth = True
    if "coarse" in mw:
        mw.remove("coarse")
        wheel_smooth = False
    if any(x in FALSE_OPTIONS for x in mw):
        return wheel_smooth, {}
    UP = 4
    LEFT = 6
    Z1 = 8
    invertall = len(mw) == 1 and mw[0] in ("invert", "invertall")
    wheel_map = {}
    for i in range(20):
        btn = 4 + i * 2
        invert = any((
            invertall,
            btn == UP and "inverty" in mw,
            btn == LEFT and "invertx" in mw,
            btn == Z1 and "invertz" in mw,
        ))
        if not invert:
            wheel_map[btn] = btn
            wheel_map[btn + 1] = btn + 1
        else:
            wheel_map[btn + 1] = btn
            wheel_map[btn] = btn + 1
    return wheel_smooth, wheel_map


class PointerClient(StubClientSubsystem):
    """
    Utility mixin for clients that handle pointer input
    """
    __slots__ = (
        "button_state", "button_transform", "middle_click", "position", "position_delay", "position_pending",
        "position_send_time", "position_timer", "sequence", "server_pointer", "server_precise_wheel", "sync",
        "wheel_deltax", "wheel_deltay", "wheel_map", "wheel_smooth",
    )
    PREFIX = "pointer"

    def __init__(self, client=None):
        StubClientSubsystem.__init__(self, client)
        self.sequence = {}
        self.sync = False
        self.position_delay = 5
        self.position: Packet | None = None
        self.position_pending: Packet | None = None
        self.position_send_time = 0
        self.position_delay = MOUSE_DELAY
        self.position_timer = 0
        self.button_transform: dict[tuple[str, int], int] = {}
        self.server_pointer = True
        self.middle_click = True
        self.button_state: dict[int, bool] = {}
        self.server_precise_wheel = False
        self.wheel_smooth: bool = SMOOTH_SCROLL
        self.wheel_map: dict[int, int] = {}
        self.wheel_deltax: float = 0
        self.wheel_deltay: float = 0

    def init(self, opts) -> None:
        # with `sharing=sync` or `sharing=sync-pointer`,
        # ask the server to forward the pointer events of the other clients,
        # so that we can show what the other users are doing:
        self.sync = is_sharing_sync(getattr(opts, "sharing", False), "pointer")
        self.wheel_smooth, self.wheel_map = parse_mousewheel(getattr(opts, "mousewheel", ""))
        log("wheel_map(%s)=%s, wheel_smooth=%s", opts.mousewheel, self.wheel_map, self.wheel_smooth)

    def init_ui(self, opts) -> None:
        self.middle_click = getattr(opts, "middle_click", True)
        pointer_opt = opts.pointer.replace("-", "").lower()
        pointer = pointer_opt.split(":", 1)[0]
        modifier = "shift" if pointer_opt.find(":") < 0 else pointer_opt.split(":", 1)[1]
        if pointer in ("emulate3buttons", "middleemulation"):
            self.button_transform[(modifier, 1)] = 2  # emulate middle button with shift+left
        if MOUSE_DELAY_AUTO:
            try:
                # some platforms don't detect the vrefresh correctly
                # (ie: macos in virtualbox?), so use a sane default minimum
                # discount by 5ms to ensure we have time to hit the target
                # weak dependency on the `display` subsystem:
                v = max(60, self.get_subsystem("display").get_vrefresh())
                self.position_delay = max(5, 1000 // v // 2 - 5)
                log(f"mouse position delay: {self.position_delay}")
            except (AttributeError, OSError):
                log("failed to calculate automatic delay", exc_info=True)

    def cleanup(self) -> None:
        self.cancel_send_mouse_position_timer()

    def get_info(self) -> dict[str, dict[str, Any]]:
        return {
            PointerClient.PREFIX: {
                "button-transform": self.button_transform,
                "buttons": self.button_state,
                "wheel": {
                    "delta-x": int(self.wheel_deltax * 1000),
                    "delta-y": int(self.wheel_deltay * 1000),
                },
            },
        }

    def get_mouse_position(self) -> tuple[int, int]:
        # delegate to the client for now, since querying the pointer position
        # requires toolkit-specific access to the root window:
        return self.client.get_mouse_position()

    def get_raw_mouse_position(self) -> tuple[int, int]:
        # unscaled version of `get_mouse_position`, delegated to the client for now:
        return self.client.get_raw_mouse_position()

    def get_caps(self) -> dict[str, Any]:
        double_click = get_double_click_caps()
        initial_position, _props = self.split_pointer_position(self.get_mouse_position())
        pointer_caps: dict[str, Any] = {
            "initial-position": initial_position,
            "double_click": double_click,
        }
        if self.sync:
            pointer_caps["sync"] = True
        caps: dict[str, Any] = {
            PointerClient.PREFIX: pointer_caps,
        }
        if BACKWARDS_COMPATIBLE:
            # grabs are advertised as `window.grabs` now (see `window/manager.py`),
            # older servers look for the flag in this namespace:
            pointer_caps["grabs"] = True
            caps["mouse"] = {
                "show": True,  # assumed available in v6
                "initial-position": initial_position,
            }
            caps["double_click"] = double_click
        return caps

    def send_positional(self, packet_type: str, *parts: PacketElement) -> None:
        # packets that include the mouse position data
        # we can cancel the pending position packets
        packet = Packet(packet_type, *parts)
        self.client._ordinary_packets.append(packet)
        self.position = None
        self.position_pending = None
        self.cancel_send_mouse_position_timer()
        self.client.have_more()

    def next_pointer_sequence(self, device_id: int) -> int:
        if device_id < 0:
            # unspecified device, don't bother with sequence numbers
            return 0
        seq = self.sequence.get(device_id, 0) + 1
        self.sequence[device_id] = seq
        return seq

    def send_mouse_position(self, device_id: int, wid: int, pos, modifiers=None, buttons=None, props=None) -> None:
        pos, position_props = self.split_pointer_position(pos)
        if "pointer" in self.get_server_packet_types() or not BACKWARDS_COMPATIBLE:
            # v5 packet type, most attributes are optional:
            attrs = dict(props or {})
            attrs.update(position_props)
            if modifiers is not None:
                attrs["modifiers"] = modifiers
            if buttons is not None:
                attrs["buttons"] = buttons
            seq = self.next_pointer_sequence(device_id)
            packet = Packet(POINTER_MOTION, device_id, seq, wid, pos, attrs)
        else:
            # pre-v5 packet format: no per-device id and no props.
            # (the legacy code used to append `props.values()` here, but the bare
            #  values cannot be reconstructed into a props dict server-side, so we
            #  simply drop them - props only reach the server via the v5 packet.)
            packet = Packet("pointer-position", wid, pos, modifiers or (), buttons or ())
        if self.position_timer:
            self.position_pending = packet
            return
        self.position_pending = packet
        now = monotonic()
        elapsed = int(1000 * (now - self.position_send_time))
        delay = self.position_delay - elapsed
        log("send_mouse_position(%s) elapsed=%i, delay left=%i", packet, elapsed, delay)
        if delay > 0:
            self.position_timer = self.timeout_add(delay, self.do_send_mouse_position)
        else:
            self.do_send_mouse_position()

    def do_send_mouse_position(self) -> None:
        self.position_timer = 0
        self.position_send_time = monotonic()
        self.position = self.position_pending
        log("do_send_mouse_position() position=%s", self.position)
        self.client.have_more()

    def cancel_send_mouse_position_timer(self) -> None:
        if mpt := self.position_timer:
            self.position_timer = 0
            self.source_remove(mpt)

    def send_button(self, device_id: int, wid: int, button: int, pressed: bool,
                    pointer, modifiers, buttons, props) -> None:
        pressed_state = self.button_state.get(button, False)
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
        self.button_state[button] = pressed
        pointer, position_props = self.split_pointer_position(pointer)
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

    def send_wheel_delta(self, device_id: int, wid: int, button: int, distance, pointer=None, props=None) -> float:
        keyboard = self.get_subsystem("keyboard")
        modifiers = keyboard.get_current_modifiers() if keyboard else ()
        buttons: Sequence[int] = ()
        log("send_wheel_delta%s precise wheel=%s, modifiers=%s, pointer=%s",
            (device_id, wid, button, distance, pointer, props), self.server_precise_wheel, modifiers, pointer)
        if self.server_precise_wheel:
            # send the exact value multiplied by 1000 (as an int)
            idist = round(distance * 1000)
            if abs(idist) > 0:
                pointer, position_props = self.split_pointer_position(pointer)
                props = dict(props or {})
                props.update(position_props)
                packet = [POINTER_WHEEL, wid,
                          button, idist,
                          pointer, modifiers, buttons, props]
                log("send_wheel_delta(..) %s", packet)
                self.send_positional(*packet)
            return 0
        # server cannot handle precise wheel,
        # so we have to use discrete events,
        # and send a click for each step:
        scaled_distance = abs(distance * MOUSE_SCROLL_MULTIPLIER / 100)
        if MOUSE_SCROLL_SQRT_SCALE:
            scaled_distance = math.sqrt(scaled_distance)
        steps = round(scaled_distance)
        for _ in range(steps):
            for state in True, False:
                self.send_button(device_id, wid, button, state, pointer, modifiers, buttons, props)
        # return remainder:
        scaled_remainder: float = steps
        if MOUSE_SCROLL_SQRT_SCALE:
            scaled_remainder = steps ** 2
        scaled_remainder = scaled_remainder * (100 / float(MOUSE_SCROLL_MULTIPLIER))
        remain_distance = float(scaled_remainder)
        signed_remain_distance = remain_distance * (-1 if distance < 0 else 1)
        return float(distance) - signed_remain_distance

    def wheel_event(self, device_id=-1, wid=0, deltax=0, deltay=0, pointer=(), props=None) -> None:
        # this is a different entry point for mouse wheel events,
        # which provides finer grained deltas (if supported by the server)
        # accumulate deltas:
        if deltax:
            self.wheel_deltax += deltax
            button = self.wheel_map.get(6 + int(self.wheel_deltax > 0), 0)  # RIGHT=7, LEFT=6
            if button > 0:
                self.wheel_deltax = self.send_wheel_delta(device_id, wid, button, self.wheel_deltax, pointer, props)
        if deltay:
            self.wheel_deltay += deltay
            button = self.wheel_map.get(5 - int(self.wheel_deltay > 0), 0)  # UP=4, DOWN=5
            if button > 0:
                self.wheel_deltay = self.send_wheel_delta(device_id, wid, button, self.wheel_deltay, pointer, props)
        log("wheel_event%s new deltas=%s,%s",
            (device_id, wid, deltax, deltay), self.wheel_deltax, self.wheel_deltay)

    def parse_server_capabilities(self, c: typedict) -> bool:
        self.server_pointer = c.boolget("pointer", True)
        # servers using a `uinput` device can handle fine grained wheel motion,
        # the others need the discrete button emulation, see `send_wheel_delta`:
        self.server_precise_wheel = c.boolget("wheel.precise", False)
        return True

    def split_pointer_position(self, position) -> tuple[tuple[int, ...], dict]:
        """Split pointer coordinates into an absolute pair and readable properties.

        Modern packets keep only ``(absolute_x, absolute_y)`` in their pointer
        field. Legacy packets retain the full coordinate tuple. Platform
        coordinate normalization applies to both formats. Window-relative
        coordinates are stored as ``window-position`` and monitor-relative
        coordinates are stored in a ``monitor`` descriptor containing its
        ``index`` and relative ``position``. The properties also retain the
        pre-normalization absolute pair as ``raw-position``.
        """
        if not position:
            return (), {}
        values = tuple(int(v) for v in position)
        if len(values) < 2:
            return values, {}
        raw_position = values[:2]
        props = {"raw-position": raw_position}
        if len(values) >= 4:
            props["window-position"] = values[2:4]
        display = self.get_subsystem("display")
        monitor = display.get_monitor_relative_position(raw_position) if display else None
        if monitor:
            index, x, y = monitor
            props["monitor"] = {
                "index": index,
                "position": (x, y),
            }
        server_position = display.get_server_position(raw_position) if display else raw_position
        if BACKWARDS_COMPATIBLE:
            return server_position + values[2:], props
        return server_position, props
