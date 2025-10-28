# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import math
from typing import Any
from collections.abc import Sequence

from xpra.os_util import gi_import, OSX, WIN32
from xpra.util.objects import typedict
from xpra.util.env import envint, envbool, IgnoreWarningsContext
from xpra.client.gtk3.window.stub_window import GtkStubWindow
from xpra.client.gtk3.window.common import mask_buttons
from xpra.log import Logger

GLib = gi_import("GLib")
Gdk = gi_import("Gdk")

log = Logger("window", "pointer")


SMOOTH_SCROLL = envbool("XPRA_SMOOTH_SCROLL", True)
SMOOTH_SCROLL_NORM = envint("XPRA_SMOOTH_SCROLL_NORM", 50 if OSX else 100)
SIMULATE_MOUSE_DOWN = envbool("XPRA_SIMULATE_MOUSE_DOWN", True)
SIMULATE_MOUSE_UP = envbool("XPRA_SIMULATE_MOUSE_UP", True)
BUTTON_POLLING_DELAY = envint("XPRA_BUTTON_POLLING_DELAY", 50)
CURSOR_IDLE_TIMEOUT = envint("XPRA_CURSOR_IDLE_TIMEOUT", 6)


GDK_SCROLL_MAP: dict[Gdk.ScrollDirection, int] = {
    Gdk.ScrollDirection.UP: 4,
    Gdk.ScrollDirection.DOWN: 5,
    Gdk.ScrollDirection.LEFT: 6,
    Gdk.ScrollDirection.RIGHT: 7,
}


def _button_resolve(button: int) -> int:
    if WIN32 and button in (4, 5):
        # On Windows "X" buttons (the extra buttons sometimes found on the
        # side of the mouse) are numbered 4 and 5, as there is a different
        # API for scroll events. Convert them into the X11 convention of 8
        # and 9.
        return button + 4
    return button


def _device_info(event) -> str:
    try:
        return event.device.get_name()
    except AttributeError:
        return ""


def _get_pointer(event) -> tuple[int, int]:
    return round(event.x_root), round(event.y_root)


def _get_relative_pointer(event) -> tuple[int, int]:
    return round(event.x), round(event.y)


def norm_scroll(value: float):
    if SMOOTH_SCROLL_NORM == 100:
        return value
    smoothed = math.pow(abs(value), SMOOTH_SCROLL_NORM / 100)
    return math.copysign(smoothed, value)


class PointerWindow(GtkStubWindow):

    def init_window(self, client, metadata: typedict, client_props: typedict) -> None:
        self.cursor_data = ()
        self.remove_pointer_overlay_timer = 0
        self.show_pointer_overlay_timer = 0
        self.button_pressed: dict[int, int] = {}
        self.button_polling_timer = 0

    def cleanup(self) -> None:
        self.cancel_show_pointer_overlay_timer()
        self.cancel_remove_pointer_overlay_timer()

    def get_info(self) -> dict[str, Any]:
        return {
            "buttons-pressed": self.button_pressed,
            "cursor-data": bool(self.cursor_data),
        }

    def get_window_event_mask(self) -> Gdk.EventMask:
        mask: Gdk.EventMask = Gdk.EventMask.POINTER_MOTION_MASK
        mask |= Gdk.EventMask.BUTTON_PRESS_MASK | Gdk.EventMask.BUTTON_RELEASE_MASK
        mask |= Gdk.EventMask.SCROLL_MASK
        if self._client.wheel_smooth:
            mask |= Gdk.EventMask.SMOOTH_SCROLL_MASK
        return mask

    def init_widget_events(self, widget) -> None:
        def motion(_w, event) -> bool:
            self._do_motion_notify_event(event)
            return True

        widget.connect("motion-notify-event", motion)

        def press(_w, event) -> bool:
            self._do_button_press_event(event)
            return True

        widget.connect("button-press-event", press)

        def release(_w, event) -> bool:
            self._do_button_release_event(event)
            return True

        widget.connect("button-release-event", release)

        def scroll(_w, event) -> bool:
            self._do_scroll_event(event)
            return True

        widget.connect("scroll-event", scroll)

    def get_mouse_event_wid(self, *_args) -> int:
        # used to be overridden in GTKClientWindowBase
        return self.wid

    ######################################################################
    # pointer overlay handling
    def set_cursor_data(self, cursor_data: Sequence) -> None:
        self.cursor_data = cursor_data
        b = self._backing
        if b:
            self.when_realized("cursor", b.set_cursor_data, cursor_data)

    def cancel_remove_pointer_overlay_timer(self) -> None:
        rpot = self.remove_pointer_overlay_timer
        log(f"cancel_remove_pointer_overlay_timer() timer={rpot}")
        if rpot:
            self.remove_pointer_overlay_timer = 0
            GLib.source_remove(rpot)

    def cancel_show_pointer_overlay_timer(self) -> None:
        rsot = self.show_pointer_overlay_timer
        log(f"cancel_show_pointer_overlay_timer() timer={rsot}")
        if rsot:
            self.show_pointer_overlay_timer = 0
            GLib.source_remove(rsot)

    def show_pointer_overlay(self, pos) -> None:
        # schedule do_show_pointer_overlay if needed
        b = self._backing
        if not b:
            return
        prev = b.pointer_overlay
        if pos is None:
            if not prev:
                return
            value = None
        else:
            if prev and prev[:2] == pos[:2]:
                return
            # store both scaled and unscaled value:
            # (the opengl client uses the raw value)
            value = pos[:2] + self.sp(*pos[:2]) + pos[2:]
        log("show_pointer_overlay(%s) previous value=%s, new value=%s", pos, prev, value)
        b.pointer_overlay = value
        if not self.show_pointer_overlay_timer:
            self.show_pointer_overlay_timer = GLib.timeout_add(10, self.do_show_pointer_overlay, prev)

    def do_show_pointer_overlay(self, prev) -> None:
        # queue a draw event at the previous and current position of the pointer
        # (so the backend will repaint / overlay the cursor image there)
        self.show_pointer_overlay_timer = 0
        b = self._backing
        if not b:
            return
        cursor_data = b.cursor_data

        def abs_coords(x, y, size) -> tuple[int, int, int, int]:
            if self.window_offset:
                x += self.window_offset[0]
                y += self.window_offset[1]
            w, h = size, size
            if cursor_data:
                w = cursor_data[3]
                h = cursor_data[4]
                xhot = cursor_data[5]
                yhot = cursor_data[6]
                x = x - xhot
                y = y - yhot
            return x, y, w, h

        value = b.pointer_overlay
        if value:
            # repaint the scale value (in window coordinates):
            x, y, w, h = abs_coords(*value[2:5])
            self.repaint(x, y, w, h)
            # clear it shortly after:
            self.schedule_remove_pointer_overlay()
        if prev:
            x, y, w, h = abs_coords(*prev[2:5])
            self.repaint(x, y, w, h)

    def schedule_remove_pointer_overlay(self, delay: int = CURSOR_IDLE_TIMEOUT * 1000) -> None:
        log(f"schedule_remove_pointer_overlay({delay})")
        self.cancel_remove_pointer_overlay_timer()
        self.remove_pointer_overlay_timer = GLib.timeout_add(delay, self.remove_pointer_overlay)

    def remove_pointer_overlay(self) -> None:
        log("remove_pointer_overlay()")
        self.remove_pointer_overlay_timer = 0
        self.show_pointer_overlay(None)

    def _do_button_press_event(self, event) -> None:
        # Gtk.Window.do_button_press_event(self, event)
        button = _button_resolve(event.button)
        self._button_action(button, event, True)

    def _do_button_release_event(self, event) -> None:
        # Gtk.Window.do_button_release_event(self, event)
        button = _button_resolve(event.button)
        self._button_action(button, event, False)

    ######################################################################
    # pointer motion

    def _do_motion_notify_event(self, event) -> None:
        # Gtk.Window.do_motion_notify_event(self, event)
        self.cancel_remove_pointer_overlay_timer()
        self.remove_pointer_overlay()
        if self._client.readonly or self._client.server_readonly or not self._client.server_pointer:
            return
        pointer_data, modifiers, buttons = self._pointer_modifiers(event)
        if self.button_polling_timer:
            self.cancel_button_polling()
            self.do_poll_buttons(pointer_data, modifiers, buttons)
            self.start_button_polling()
        wid = self.get_mouse_event_wid(*pointer_data)
        log("do_motion_notify_event(%s) wid=%#x / focus=%s / window wid=%#x",
            event, wid, self._client._focused, self.wid)
        log(" device=%s, pointer=%s, modifiers=%s, buttons=%s",
            _device_info(event), pointer_data, modifiers, buttons)
        device_id = 0
        self._client.send_mouse_position(device_id, wid, pointer_data, modifiers, buttons)

    def get_mouse_position(self) -> tuple[int, int]:
        # this method is used on some platforms
        # to get the pointer position for events that don't include it
        # (ie: wheel events)
        x, y = self._client.get_raw_mouse_position()
        return self._offset_pointer(x, y)

    def _offset_pointer(self, x: int, y: int) -> tuple[int, int]:
        if self.window_offset:
            x -= self.window_offset[0]
            y -= self.window_offset[1]
        return self.cp(x, y)

    def get_pointer_data(self, event) -> tuple[int, int, int, int]:
        x, y = _get_pointer(event)
        rx, ry = _get_relative_pointer(event)
        return self.adjusted_pointer_data(x, y, rx, ry)

    def adjusted_pointer_data(self, x: int, y: int, rx: int = 0, ry: int = 0) -> tuple[int, int, int, int]:
        # regular pointer coordinates are translated and scaled,
        # relative coordinates are scaled only:
        ox, oy = self._offset_pointer(x, y)
        cx, cy = self.cp(rx, ry)
        return ox, oy, cx, cy

    def _pointer_modifiers(self, event) -> tuple[tuple[int, int, int, int], list[str], list[int]]:
        pointer_data = self.get_pointer_data(event)
        # FIXME: state is used for both mods and buttons??
        modifiers = self._client.mask_to_names(event.state)
        buttons = mask_buttons(event.state)
        v = pointer_data, modifiers, buttons
        log("pointer_modifiers(%s)=%s (x_root=%s, y_root=%s, window_offset=%s)",
            event, v, event.x_root, event.y_root, self.window_offset)
        return v

    def _do_scroll_event(self, event) -> bool:
        if self._client.readonly:
            return True
        if event.direction == Gdk.ScrollDirection.SMOOTH:
            log("smooth scroll event: %s, raw delta: %s,%s", event, event.delta_x, event.delta_y)
            pointer = self.get_pointer_data(event)
            device_id = -1
            norm_x = norm_scroll(event.delta_x)
            norm_y = norm_scroll(event.delta_y)
            self._client.wheel_event(device_id, self.wid, norm_x, -norm_y, pointer)
            return True
        button_mapping = GDK_SCROLL_MAP.get(event.direction, -1)
        log("do_scroll_event device=%s, direction=%s, button_mapping=%s",
            _device_info(event), event.direction, button_mapping)
        if button_mapping >= 0:
            self._button_action(button_mapping, event, True)
            self._button_action(button_mapping, event, False)
        return True

    def translate_button(self, button: int, modifiers: list[str]) -> int:
        transform = self._client._button_transform
        if not transform:
            return button
        for modifier in modifiers:
            trans = transform.get((modifier, button), -1)
            if trans >= 0:
                log("translate_button(%i, %s) -> %s", button, modifiers, trans)
                # we could consume the modifier,
                # but pointer motion events would still include it
                return trans
        return button

    def _button_action(self, button: int, event, depressed: bool, props=None) -> None:
        if self._client.readonly or self._client.server_readonly or not self._client.server_pointer:
            return
        pointer_data, modifiers, buttons = self._pointer_modifiers(event)
        wid = self.get_mouse_event_wid(*pointer_data)
        log("_button_action(%s, %s, %s) wid=%#x / focus=%s / window wid=%#x",
            button, event, depressed, wid, self._client._focused, self.wid)
        log(" device=%s, pointer=%s, modifiers=%s, buttons=%s",
            _device_info(event), pointer_data, modifiers, buttons)
        device_id = 0

        def send_button(server_button, pressed, **kwargs) -> None:
            sprops = props or {}
            sprops.update(kwargs)
            self._client.send_button(device_id, wid, server_button, pressed, pointer_data, modifiers, buttons, sprops)

        server_button = -1
        if not depressed:
            # we should have a record of which button press event was sent:
            server_button = self.button_pressed.get(button, -1)
            if SIMULATE_MOUSE_DOWN and server_button < 0:
                log("button action: simulating missing mouse-down event for window %s before mouse-up", wid)
                # (needed for some dialogs on win32):
                server_button = self.translate_button(button, modifiers)
                send_button(server_button, True, synthetic=True)

        if server_button < 0:
            server_button = self.translate_button(button, modifiers)

        if depressed:
            self.button_pressed[button] = server_button
        else:
            self.button_pressed.pop(button, None)
            if not self.button_pressed:
                self.cancel_button_polling()
        send_button(server_button, depressed)

    def cancel_button_polling(self) -> None:
        log("cancel_button_polling()")
        bpt = self.button_polling_timer
        if bpt:
            self.button_polling_timer = 0
            GLib.source_remove(bpt)

    def start_button_polling(self) -> None:
        log("start_button_polling()")
        if self.button_polling_timer:
            return
        self.button_polling_timer = GLib.timeout_add(BUTTON_POLLING_DELAY, self.poll_buttons)

    def poll_buttons(self) -> bool:
        with IgnoreWarningsContext():
            x, y, mask = self.get_root_window().get_pointer()[-3:]
        buttons = mask_buttons(mask)
        modifiers = self._client.mask_to_names(mask)
        self.do_poll_buttons((x, y), modifiers, buttons)
        if not self.button_pressed:
            self.button_polling_timer = 0
            return False
        return True

    def do_poll_buttons(self, pointer_data: Sequence[int], modifiers: list[str], buttons: Sequence[int]) -> None:
        pressed = tuple(self.button_pressed.keys())
        log("do_poll_buttons(%s, %s) pressed=%s", pointer_data, buttons, pressed)
        for button in pressed:
            if button not in buttons:
                log(f"button {button=} unpressed")
                if SIMULATE_MOUSE_UP:
                    device_id = 0
                    wid = self.get_mouse_event_wid()
                    server_button = self.translate_button(button, modifiers)
                    sprops = {}
                    self._client.send_button(device_id, wid, server_button, False, pointer_data, modifiers, buttons,
                                             sprops)
                    self.button_pressed.pop(button, None)

    def do_button_press_event(self, event) -> None:
        self._button_action(event.button, event, True)

    def do_button_release_event(self, event) -> None:
        self._button_action(event.button, event, False)
