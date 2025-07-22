# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from typing import Any
from time import monotonic

from xpra.client.base.stub import StubClientMixin
from xpra.common import BACKWARDS_COMPATIBLE
from xpra.net.common import Packet, PacketElement
from xpra.util.objects import typedict
from xpra.util.env import envbool, envint
from xpra.os_util import gi_import
from xpra.log import Logger

log = Logger("pointer")

GLib = gi_import("GLib")

MOUSE_DELAY = envint("XPRA_MOUSE_DELAY", 0)
MOUSE_DELAY_AUTO = envbool("XPRA_MOUSE_DELAY_AUTO", True)


def get_double_click_caps() -> dict[str, Any]:
    from xpra.platform.gui import get_double_click_time, get_double_click_distance
    return {
        "time": get_double_click_time(),
        "distance": get_double_click_distance(),
    }


class PointerClient(StubClientMixin):
    """
    Utility mixin for clients that handle pointer input
    """
    PREFIX = "pointer"

    def __init__(self):
        self._pointer_sequence = {}
        self._mouse_position_delay = 5
        self._mouse_position: Packet | None = None
        self._mouse_position_pending: Packet | None = None
        self._mouse_position_send_time = 0
        self._mouse_position_delay = MOUSE_DELAY
        self._mouse_position_timer = 0
        self._button_transform: dict[tuple[str, int], int] = {}
        self.server_pointer = True

    def init_ui(self, opts) -> None:
        pointer_opt = opts.pointer.replace("-", "").lower()
        pointer = pointer_opt.split(":", 1)[0]
        modifier = "shift" if pointer_opt.find(":") < 0 else pointer_opt.split(":", 1)[1]
        if pointer in ("emulate3buttons", "middleemulation"):
            self._button_transform[(modifier, 1)] = 2  # emulate middle button with shift+left
        if MOUSE_DELAY_AUTO:
            try:
                # some platforms don't detect the vrefresh correctly
                # (ie: macos in virtualbox?), so use a sane default minimum
                # discount by 5ms to ensure we have time to hit the target
                v = max(60, self.get_vrefresh())
                self._mouse_position_delay = max(5, 1000 // v // 2 - 5)
                log(f"mouse position delay: {self._mouse_position_delay}")
            except (AttributeError, OSError):
                log("failed to calculate automatic delay", exc_info=True)

    def cleanup(self) -> None:
        self.cancel_send_mouse_position_timer()

    def get_info(self) -> dict[str, dict[str, Any]]:
        return {PointerClient.PREFIX: {"button-transform": self._button_transform}}

    def get_caps(self) -> dict[str, Any]:
        # the gtk client implements `get_mouse_position`
        def get_mouse_position() -> tuple[int, int]:
            if hasattr(self, "get_mouse_position"):
                return self.get_mouse_position()
            return -1, -1

        double_click = get_double_click_caps()
        caps: dict[str, Any] = {
            PointerClient.PREFIX: {
                "initial-position": get_mouse_position(),
                "double_click": double_click,
            },
        }
        if BACKWARDS_COMPATIBLE:
            caps["mouse"] = {
                "show": True,  # assumed available in v6
                "initial-position": get_mouse_position(),
            }
            caps["double_click"] = double_click
        return caps

    def send_positional(self, packet_type: str, *parts: PacketElement) -> None:
        # packets that include the mouse position data
        # we can cancel the pending position packets
        packet = Packet(packet_type, *parts)
        self._ordinary_packets.append(packet)
        self._mouse_position = None
        self._mouse_position_pending = None
        self.cancel_send_mouse_position_timer()
        self.have_more()

    def next_pointer_sequence(self, device_id: int) -> int:
        if device_id < 0:
            # unspecified device, don't bother with sequence numbers
            return 0
        seq = self._pointer_sequence.get(device_id, 0) + 1
        self._pointer_sequence[device_id] = seq
        return seq

    def send_mouse_position(self, device_id: int, wid: int, pos, modifiers=None, buttons=None, props=None) -> None:
        if "pointer" in self.server_packet_types:
            # v5 packet type, most attributes are optional:
            attrs = props or {}
            if modifiers is not None:
                attrs["modifiers"] = modifiers
            if buttons is not None:
                attrs["buttons"] = buttons
            seq = self.next_pointer_sequence(device_id)
            packet = Packet("pointer", device_id, seq, wid, pos, attrs)
        else:
            # pre v5 packet format:
            packet = Packet("pointer-position", wid, pos, modifiers or (), buttons or ())
            if props:
                packet += props.values()
        if self._mouse_position_timer:
            self._mouse_position_pending = packet
            return
        self._mouse_position_pending = packet
        now = monotonic()
        elapsed = int(1000 * (now - self._mouse_position_send_time))
        delay = self._mouse_position_delay - elapsed
        log("send_mouse_position(%s) elapsed=%i, delay left=%i", packet, elapsed, delay)
        if delay > 0:
            self._mouse_position_timer = GLib.timeout_add(delay, self.do_send_mouse_position)
        else:
            self.do_send_mouse_position()

    def do_send_mouse_position(self) -> None:
        self._mouse_position_timer = 0
        self._mouse_position_send_time = monotonic()
        self._mouse_position = self._mouse_position_pending
        log("do_send_mouse_position() position=%s", self._mouse_position)
        self.have_more()

    def cancel_send_mouse_position_timer(self) -> None:
        mpt = self._mouse_position_timer
        if mpt:
            self._mouse_position_timer = 0
            GLib.source_remove(mpt)

    def parse_server_capabilities(self, c: typedict) -> bool:
        self.server_pointer = c.boolget("pointer", True)
        return True
