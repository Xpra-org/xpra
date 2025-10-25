# This file is part of Xpra.
# Copyright (C) 2011 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from typing import Sequence, Any

from xpra.platform.posix.gui import X11XI2Bindings, X11WindowBindings
from xpra.util.env import envint
from xpra.util.str_fn import csv
from xpra.log import Logger

log = Logger("posix")
xinputlog = Logger("posix", "xinput")
pointerlog = Logger("posix", "pointer")

XINPUT_WHEEL_DIV = envint("XPRA_XINPUT_WHEEL_DIV", 15)


def suppress_event(*_args) -> None:
    """ we'll use XI2 to receive events """


def intscaled(f) -> tuple[int, int]:
    return round(f * 1000000), 1000000


def dictscaled(d) -> dict[Any, tuple[int, int]]:
    return {k: intscaled(v) for k, v in d.items()}


class XI2_Window:
    """
    The posix client will call XI2_Window on every Gtk window that it manages
    via `add_window_hooks`.
    """
    def __init__(self, window):
        log("XI2_Window(%s)", window)
        self.XI2 = X11XI2Bindings()
        self.X11Window = X11WindowBindings()
        self.window = window
        self.xid = window.get_window().get_xid()
        self.windows: Sequence[int] = ()
        self.motion_valuators = {}
        window.connect("configure-event", self.configured)
        self.configured()
        # replace event handlers with XI2 version:
        self._do_motion_notify_event = window._do_motion_notify_event
        window._do_motion_notify_event = suppress_event
        window._do_button_press_event = suppress_event
        window._do_button_release_event = suppress_event
        window._do_scroll_event = suppress_event
        window.connect("destroy", self.cleanup)

    def cleanup(self, *_args) -> None:
        for window in self.windows:
            self.XI2.disconnect(window)
        self.windows = ()
        self.window = None

    def configured(self, *_args) -> None:
        from xpra.x11.error import xlog
        with xlog:
            self.windows = self.get_parent_windows(self.xid)
        for window in (self.windows or ()):
            self.XI2.connect(window, "XI_Motion", self.do_xi_motion)
            self.XI2.connect(window, "XI_ButtonPress", self.do_xi_button)
            self.XI2.connect(window, "XI_ButtonRelease", self.do_xi_button)
            self.XI2.connect(window, "XI_DeviceChanged", self.do_xi_device_changed)
            self.XI2.connect(window, "XI_HierarchyChanged", self.do_xi_hierarchy_changed)

    def do_xi_device_changed(self, *_args) -> None:
        self.motion_valuators = {}

    def do_xi_hierarchy_changed(self, *_args) -> None:
        self.motion_valuators = {}

    def get_parent_windows(self, oxid: int) -> Sequence[int]:
        windows = [oxid]
        root = self.X11Window.get_root_xid()
        xid = oxid
        while True:
            xid = self.X11Window.getParent(xid)
            if xid == 0 or xid == root:
                break
            windows.append(xid)
        xinputlog("get_parent_windows(%#x)=%s", oxid, csv(hex(x) for x in windows))
        return tuple(windows)

    def do_xi_button(self, event, device) -> None:
        window = self.window
        client = window._client
        if client.readonly:
            return
        xinputlog("do_xi_button(%s, %s) server_input_devices=%s", event, device, client.server_input_devices)
        if client.server_input_devices == "xi" or (
                client.server_input_devices == "uinput" and client.server_precise_wheel):
            # skip synthetic scroll events,
            # as the server should synthesize them from the motion events
            # those have the same serial:
            matching_motion = self.XI2.find_event("XI_Motion", event.serial)
            # maybe we need more to distinguish?
            if matching_motion:
                return
        button = event.detail
        depressed = (event.name == "XI_ButtonPress")
        props = self.get_pointer_extra_args(event)
        window._button_action(button, event, depressed, props)

    def do_xi_motion(self, event, device) -> None:
        window = self.window
        if window.moveresize_event:
            xinputlog("do_xi_motion(%s, %s) handling as a moveresize event on window %s", event, device, window)
            window.motion_moveresize(event)
            self._do_motion_notify_event(event)
            return
        client = window._client
        if client.readonly:
            return
        pointer_data, modifiers, buttons = window._pointer_modifiers(event)
        wid = self.window.get_mouse_event_wid(*pointer_data)
        # log("server_input_devices=%s, server_precise_wheel=%s",
        #    client.server_input_devices, client.server_precise_wheel)
        valuators = event.valuators
        unused_valuators = valuators.copy()
        dx, dy = 0, 0
        if (
                valuators and device and device.get("enabled")
                and client.server_input_devices == "uinput"  # noqa W503
                and client.server_precise_wheel  # noqa W503
        ):
            XIModeRelative = 0
            classes = device.get("classes")
            val_classes = {}
            for c in classes.values():
                number = c.get("number")
                if number is not None and c.get("type") == "valuator" and c.get("mode") == XIModeRelative:
                    val_classes[number] = c
            # previous values:
            mv = self.motion_valuators.setdefault(event.device, {})
            last_x, last_y = 0, 0
            wheel_x, wheel_y = 0, 0
            unused_valuators = {}
            for number, value in valuators.items():
                valuator = val_classes.get(number)
                if valuator:
                    label = valuator.get("label")
                    if label:
                        pointerlog("%s: %s", label, value)
                        if label.lower().find("horiz") >= 0:
                            wheel_x = value
                            last_x = mv.get(number)
                            continue
                        elif label.lower().find("vert") >= 0:
                            wheel_y = value
                            last_y = mv.get(number)
                            continue
                unused_valuators[number] = value
            # new absolute motion values:
            # calculate delta if we have both old and new values:
            if last_x is not None and wheel_x is not None:
                dx = last_x - wheel_x
            if last_y is not None and wheel_y is not None:
                dy = last_y - wheel_y
            # whatever happens, update our motion cached values:
            mv.update(event.valuators)
        # send plain motion first, if any:
        props = self.get_pointer_extra_args(event)
        if unused_valuators:
            xinputlog("do_xi_motion(%s, %s) wid=%#x / focus=%s / window wid=%#x",
                      event, device, wid, window._client._focused, window.wid)
            xinputlog(" device=%s, pointer=%s, modifiers=%s, buttons=%s",
                      event.device, pointer_data, modifiers, buttons)
            device_id = 0
            client.send_mouse_position(device_id, wid, pointer_data, modifiers, buttons, props)
        # now see if we have anything to send as a wheel event:
        if dx != 0 or dy != 0:
            xinputlog("do_xi_motion(%s, %s) wheel deltas: dx=%i, dy=%i", event, device, dx, dy)
            # normalize (xinput is always using 15 degrees?)
            client.wheel_event(event.device, wid, dx / XINPUT_WHEEL_DIV, dy / XINPUT_WHEEL_DIV, pointer_data, props)

    def get_pointer_extra_args(self, event) -> dict[str, Any]:
        props = {
            "device": event.device,
        }
        for k in ("x", "y", "x_root", "y_root"):
            props[k] = intscaled(getattr(event, k))
        props["valuators"] = dictscaled(event.valuators or {})
        raw_event_name = event.name.replace("XI_", "XI_Raw")  # ie: XI_Motion -> XI_RawMotion
        raw = self.XI2.find_event(raw_event_name, event.serial)
        props["raw-valuators"] = dictscaled(raw.raw_valuators if raw else {})
        return props
