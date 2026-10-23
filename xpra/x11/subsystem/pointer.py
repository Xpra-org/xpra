# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.
# pylint: disable-msg=E1101

from typing import Any

from xpra.net.common import Packet
from xpra.server.subsystem.pointer import PointerManager
from xpra.log import Logger

log = Logger("pointer")


class X11PointerManager(PointerManager):
    __slots__ = ("input_devices_format",)

    def __init__(self, server=None):
        PointerManager.__init__(self, server)
        self.input_devices_format = ""

    def init(self, opts) -> None:
        super().init(opts)
        if self.input_devices == "auto":
            self.input_devices = "xtest"

    def make_pointer_device(self):
        try:
            from xpra.x11.server.xtest_pointer import XTestPointerDevice
            return XTestPointerDevice()
        except ImportError as e:
            log.warn("Warning: unable to import XTest bindings")
            log.warn(" %s", e)
        return None

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
        from xpra.x11.server.xtest_pointer import XTestPointerDevice
        xtest = XTestPointerDevice()
        if pointer:
            uinput_device = pointer.get("uinput")
            device_path = pointer.get("device")
            if uinput_device:
                from xpra.uinput.device import UInputPointerDevice
                self.input_devices = "uinput"
                self.pointer_device = UInputPointerDevice(uinput_device, device_path, xtest)
                self.send_dummy_wheel_event(self.pointer_device)
                self.verify_uinput_pointer_device(xtest)
        if self.input_devices == "uinput" and touchpad:
            uinput_device = touchpad.get("uinput")
            device_path = touchpad.get("device")
            if uinput_device:
                from xpra.uinput.device import UInputTouchpadDevice
                root_w, root_h = display.get_display_size()
                self.touchpad_device = UInputTouchpadDevice(uinput_device, device_path, xtest, root_w, root_h)
                self.send_dummy_wheel_event(self.touchpad_device)
                # `display-geometry-changed` is a subsystem-local signal
                # owned by `DisplayManager` (via `SignalEmitter`):
                display.connect("display-geometry-changed", self.update_touchpad_size)
        if self.pointer_device:
            try:
                log.info("pointer device emulation using %r", str(self.pointer_device).replace("PointerDevice", ""))
            except Exception as e:
                log("cannot get pointer device class from %s: %s", self.pointer_device, e)

    @staticmethod
    def send_dummy_wheel_event(device) -> None:
        # the first event always goes MIA:
        # http://who-t.blogspot.co.at/2012/06/xi-21-protocol-design-issues.html
        # so synthesize a dummy one now:
        from xpra.x11.error import xlog
        with xlog:
            # pylint: disable=no-name-in-module, import-outside-toplevel
            from xpra.x11.bindings.xi2 import X11XI2Bindings
            v = X11XI2Bindings().get_xi_version()
            log("XInput version %s", ".".join(str(x) for x in v))
            if v <= (2, 2):
                device.wheel_motion(4, 1)

    def verify_uinput_pointer_device(self, xtest) -> None:
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

    # noinspection unreachable-code
    def get_pointer_position(self) -> tuple[int, int]:
        from xpra.x11.bindings.core import X11CoreBindings
        from xpra.x11.error import xswallow
        with xswallow:
            return X11CoreBindings().query_pointer()
        return 0, 0

    def _process_devices(self, _proto, packet: Packet) -> None:
        self.input_devices_format = packet.get_str(1)
        self.input_devices_data = packet.get_dict(2)
        from xpra.util.str_fn import print_nested_dict
        log("client %s input devices:", self.input_devices_format)
        print_nested_dict(self.input_devices_data, print_fn=log)
        self.setup_input_devices()

    def setup_input_devices(self) -> None:
        log("setup_input_devices()")
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
        super().init_packet_handlers()
        self.add_packets(
            "pointer-devices",
            main_thread=True
        )
