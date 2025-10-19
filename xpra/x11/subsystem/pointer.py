# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.
# pylint: disable-msg=E1101

from xpra.net.common import Packet
from xpra.server.subsystem.pointer import PointerServer
from xpra.log import Logger

log = Logger("pointer")


class X11PointerServer(PointerServer):

    def __init__(self):
        PointerServer.__init__(self)
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

    def _process_input_devices(self, _proto, packet: Packet) -> None:
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
            "input-devices",
            main_thread=True
        )
