# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import math
from typing import Any
from collections.abc import Sequence

from xpra.util.parsing import FALSE_OPTIONS
from xpra.os_util import OSX
from xpra.util.objects import typedict
from xpra.util.env import envint, envbool
from xpra.client.base.stub import StubClientMixin
from xpra.log import Logger

log = Logger("window", "pointer")

SMOOTH_SCROLL: bool = envbool("XPRA_SMOOTH_SCROLL", True)

MOUSE_SCROLL_SQRT_SCALE: bool = envbool("XPRA_MOUSE_SCROLL_SQRT_SCALE", OSX)
MOUSE_SCROLL_MULTIPLIER: int = envint("XPRA_MOUSE_SCROLL_MULTIPLIER", 100)


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


class WindowWheel(StubClientMixin):

    def __init__(self):
        self.server_precise_wheel: bool = False
        self.wheel_smooth: bool = SMOOTH_SCROLL
        self.wheel_map = {}
        self.wheel_deltax: float = 0
        self.wheel_deltay: float = 0

    def init(self, opts) -> None:
        self.wheel_smooth, wheel_map = parse_mousewheel(opts.mousewheel)
        self.wheel_map.update(wheel_map)
        log("wheel_map(%s)=%s, wheel_smooth=%s", opts.mousewheel, self.wheel_map, self.wheel_smooth)

    def get_info(self) -> dict[str, Any]:
        info: dict[Any, Any] = {
            "wheel": {
                "delta-x": int(self.wheel_deltax * 1000),
                "delta-y": int(self.wheel_deltay * 1000),
            },
        }
        return info

    def parse_server_capabilities(self, c: typedict) -> bool:
        self.server_precise_wheel = c.boolget("wheel.precise", False)
        return True

    def send_wheel_delta(self, device_id: int, wid: int, button: int, distance, pointer=None, props=None) -> float:
        modifiers = self.get_current_modifiers()
        buttons: Sequence[int] = ()
        log("send_wheel_delta%s precise wheel=%s, modifiers=%s, pointer=%s",
            (device_id, wid, button, distance, pointer, props), self.server_precise_wheel, modifiers, pointer)
        if self.server_precise_wheel:
            # send the exact value multiplied by 1000 (as an int)
            idist = round(distance * 1000)
            if abs(idist) > 0:
                packet = ["wheel-motion", wid,
                          button, idist,
                          pointer, modifiers, buttons] + list((props or {}).values())
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
