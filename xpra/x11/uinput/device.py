# This file is part of Xpra.
# Copyright (C) 2017 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from uinput import (
    BTN_LEFT, BTN_RIGHT, BTN_MIDDLE, BTN_SIDE, BTN_EXTRA,  # @UnresolvedImport
    REL_WHEEL, REL_HWHEEL,  # @UnresolvedImport
    REL_X, REL_Y, BTN_TOUCH, ABS_X, ABS_Y, ABS_PRESSURE,  # @UnresolvedImport
)

from xpra.util.env import envint
from xpra.x11.bindings.keyboard import X11KeyboardBindings
from xpra.gtk.error import xsync, xlog
from xpra.log import Logger

log = Logger("x11", "server", "pointer")

X11Keyboard = X11KeyboardBindings()

MOUSE_WHEEL_CLICK_MULTIPLIER = envint("XPRA_MOUSE_WHEEL_CLICK_MULTIPLIER", 30)

BUTTON_STR = {
    BTN_LEFT: "BTN_LEFT",
    BTN_RIGHT: "BTN_RIGHT",
    BTN_MIDDLE: "BTN_MIDDLE",
    BTN_SIDE: "BTN_SIDE",
    BTN_EXTRA: "BTN_EXTRA",
    REL_WHEEL: "REL_WHEEL",
    REL_HWHEEL: "REL_HWHEEL",
}
BUTTON_MAP: dict[int, tuple[int, int]] = {
    1: BTN_LEFT,
    3: BTN_RIGHT,
    2: BTN_MIDDLE,
    8: BTN_SIDE,
    9: BTN_EXTRA,
}


class UInputDevice:
    __slots__ = ("device", "device_path", "wheel_delta")

    def __init__(self, device, device_path):
        self.device = device
        self.device_path: str = device_path
        self.wheel_delta: dict[int, float] = {}
        # the first event always goes MIA:
        # http://who-t.blogspot.co.at/2012/06/xi-21-protocol-design-issues.html
        # so synthesize a dummy one now:
        with xlog:
            # pylint: disable=no-name-in-module, import-outside-toplevel
            from xpra.x11.bindings.xi2 import X11XI2Bindings
            xi2 = X11XI2Bindings()
            v = xi2.get_xi_version()
            log("XInput version %s", ".".join(str(x) for x in v))
            if v <= (2, 2):
                self.wheel_motion(4, 1)

    def click(self, button: int, pressed: bool, _props) -> None:
        # this multiplier is based on the values defined in 71-xpra-virtual-pointer.rules as:
        # MOUSE_WHEEL_CLICK_COUNT=360
        # MOUSE_WHEEL_CLICK_ANGLE=1
        mult = MOUSE_WHEEL_CLICK_MULTIPLIER
        if button == 4:
            ubutton = REL_WHEEL
            val = 1 * mult
            if pressed:  # only send one event
                return
        elif button == 5:
            ubutton = REL_WHEEL
            val = -1 * mult
            if pressed:  # only send one event
                return
        elif button == 6:
            ubutton = REL_HWHEEL
            val = 1 * mult
            if pressed:  # only send one event
                return
        elif button == 7:
            ubutton = REL_HWHEEL
            val = -1 * mult
            if pressed:  # only send one event
                return
        else:
            ubutton = BUTTON_MAP.get(button)
            val = bool(pressed)
        if ubutton:
            log("UInput.click(%i, %s) uinput button=%s (%#x), %#x, value=%s",
                button, pressed, BUTTON_STR.get(ubutton), ubutton[0], ubutton[1], val)
            self.device.emit(ubutton, val)
        else:
            log("UInput.click(%i, %s) uinput button not found - using XTest", button, pressed)
            X11Keyboard.xtest_fake_button(button, pressed)

    def wheel_motion(self, button: int, distance: float) -> None:
        if button in (4, 5):
            val = distance * MOUSE_WHEEL_CLICK_MULTIPLIER
            ubutton = REL_WHEEL
        elif button in (6, 7):
            val = distance * MOUSE_WHEEL_CLICK_MULTIPLIER
            ubutton = REL_HWHEEL
        else:
            log.warn("Warning: %s", self)
            log.warn(" cannot handle wheel motion %i", button)
            log.warn(" this event has been dropped")
            return
        saved = self.wheel_delta.get(ubutton, 0)
        delta = saved + val
        ival = round(delta)
        log("UInput.wheel_motion(%i, %.4f) %s: %s+%s=%s, will emit %i",
            button, distance, BUTTON_STR.get(ubutton), saved, val, delta, ival)
        if ival != 0:
            self.device.emit(ubutton, ival)
        self.wheel_delta[ubutton] = delta - ival

    def has_precise_wheel(self) -> bool:
        return True


class UInputPointerDevice(UInputDevice):

    def __repr__(self):
        return "UInput pointer device %s" % self.device_path

    def move_pointer(self, x: int, y: int, props=None) -> None:
        log("UInputPointerDevice.move_pointer(%i, %s, %s)", x, y, props)
        # calculate delta:
        with xsync:
            cx, cy = X11Keyboard.query_pointer()
            log("X11Keyboard.query_pointer=%s, %s", cx, cy)
            dx = x - cx
            dy = y - cy
            log("delta(%s, %s)=%s, %s", cx, cy, dx, dy)
        # self.device.emit(ABS_X, x, syn=(dy==0))
        # self.device.emit(ABS_Y, y, syn=True)
        if dx or dy:
            if dx != 0:
                self.device.emit(REL_X, dx, syn=(dy == 0))
            if dy != 0:
                self.device.emit(REL_Y, dy, syn=True)


class UInputTouchpadDevice(UInputDevice):
    __slots__ = ("root_w", "root_h")

    def __init__(self, device, device_path, root_w, root_h):
        super().__init__(device, device_path)
        self.root_w = root_w
        self.root_h = root_h

    def __repr__(self):
        return "UInput touchpad device %s" % self.device_path

    def move_pointer(self, x: int, y: int, props=None) -> None:
        log("UInputTouchpadDevice.move_pointer(%s, %s, %s)", x, y, props)
        self.device.emit(BTN_TOUCH, 1, syn=False)
        self.device.emit(ABS_X, x * (2 ** 24) // self.root_w, syn=False)
        self.device.emit(ABS_Y, y * (2 ** 24) // self.root_h, syn=False)
        self.device.emit(ABS_PRESSURE, 255, syn=False)
        self.device.emit(BTN_TOUCH, 0, syn=True)
        with xsync:
            cx, cy = X11Keyboard.query_pointer()
            log("X11Keyboard.query_pointer=%s, %s", cx, cy)
