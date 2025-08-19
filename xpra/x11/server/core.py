# This file is part of Xpra.
# Copyright (C) 2011 Serviware (Arthur Huillet, <ahuillet@serviware.com>)
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import threading
from typing import Any

from xpra.os_util import gi_import
from xpra.x11.bindings.core import set_context_check
from xpra.x11.error import XError, xswallow, xsync, xlog, verify_sync
from xpra.common import noerr
from xpra.util.objects import typedict
from xpra.util.env import envbool
from xpra.server.base import ServerBase
from xpra.log import Logger

GLib = gi_import("GLib")

set_context_check(verify_sync)

log = Logger("x11", "server")
keylog = Logger("x11", "server", "keyboard")
pointerlog = Logger("x11", "server", "pointer")

ALWAYS_NOTIFY_MOTION = envbool("XPRA_ALWAYS_NOTIFY_MOTION", False)


class X11ServerCore(ServerBase):
    """
        Base class for X11 servers,
        adds X11 specific methods to ServerBase.
        (see XpraServer or XpraX11ShadowServer for actual implementations)
    """

    def init_uuid(self) -> None:
        super().init_uuid()
        with xlog:
            self.save_server_mode()
            self.save_server_uuid()

    def save_server_mode(self) -> None:
        from xpra.x11.xroot_props import root_set
        root_set("XPRA_SERVER_MODE", "latin1", self.session_type)

    def do_cleanup(self) -> None:
        # prop_del does its own xsync:
        noerr(self.clean_x11_properties)
        super().do_cleanup()
        from xpra.x11.dispatch import cleanup_all_event_receivers
        cleanup_all_event_receivers()

    def clean_x11_properties(self) -> None:
        self.do_clean_x11_properties("XPRA_SERVER_MODE", "_XPRA_RANDR_EXACT_SIZE", "XPRA_SERVER_PID")

    # noinspection PyMethodMayBeStatic
    def do_clean_x11_properties(self, *properties) -> None:
        from xpra.x11.xroot_props import root_del
        for prop in properties:
            try:
                root_del(prop)
            except Exception as e:
                log.warn(f"Warning: failed to delete property {prop!r} on root window: {e}")

    # noinspection PyMethodMayBeStatic
    def get_server_uuid(self) -> str:
        from xpra.x11.xroot_props import root_get
        return root_get("XPRA_SERVER_UUID", "latin1") or ""

    def save_server_uuid(self) -> None:
        from xpra.x11.xroot_props import root_set
        root_set("XPRA_SERVER_UUID", "latin1", self.uuid)

    def make_hello(self, source) -> dict[str, Any]:
        capabilities = super().make_hello(source)
        capabilities["server_type"] = "Python/x11"
        return capabilities

    def get_ui_info(self, proto, wids=None, *args) -> dict[str, Any]:
        log("do_get_info thread=%s", threading.current_thread())
        info = super().get_ui_info(proto, wids, *args)
        # this is added here because the server keyboard config doesn't know about "keys_pressed"..
        sinfo = info.setdefault("server", {})
        try:
            from xpra.x11.composite import CompositeHelper
            sinfo["XShm"] = CompositeHelper.XShmEnabled
        except (ImportError, ValueError) as e:
            log("no composite: %s", e)
        return info

    def get_window_info(self, window) -> dict[str, Any]:
        info = super().get_window_info(window)
        info["XShm"] = window.uses_xshm()
        info["geometry"] = window.get_geometry()
        return info

    # noinspection PyMethodMayBeStatic
    def get_keyboard_config(self, props=None):
        p = typedict(props or {})
        from xpra.x11.server.keyboard_config import KeyboardConfig
        keyboard_config = KeyboardConfig()
        keyboard_config.enabled = p.boolget("keyboard", True)
        keyboard_config.parse_options(p)
        keyboard_config.parse_layout(p)
        keylog("get_keyboard_config(..)=%s", keyboard_config)
        return keyboard_config

    def set_keymap(self, server_source, force=False) -> None:
        if self.readonly:
            return

        def reenable_keymap_changes(*args) -> bool:
            keylog("reenable_keymap_changes(%s)", args)
            self.keymap_changing_timer = 0
            self._keys_changed()
            return False

        # prevent _keys_changed() from firing:
        # (using a flag instead of keymap.disconnect(handler) as this did not seem to work!)
        if not self.keymap_changing_timer:
            # use idle_add to give all the pending
            # events a chance to run first (and get ignored)
            self.keymap_changing_timer = GLib.timeout_add(100, reenable_keymap_changes)
        # if sharing, don't set the keymap, translate the existing one:
        other_ui_clients = [s.uuid for s in self._server_sources.values() if s != server_source and s.ui_client]
        translate_only = len(other_ui_clients) > 0
        keylog("set_keymap(%s, %s) translate_only=%s", server_source, force, translate_only)
        with xsync:
            # pylint: disable=access-member-before-definition
            server_source.set_keymap(self.keyboard_config, self.keys_pressed, force, translate_only)
            self.keyboard_config = server_source.keyboard_config

    def _motion_signaled(self, model, event) -> None:
        pointerlog("motion_signaled(%s, %s) last mouse user=%s", model, event, self.last_mouse_user)
        # find the window model for this gdk window:
        wid = self._window_to_id.get(model)
        if not wid:
            return
        for ss in self._server_sources.values():
            if ALWAYS_NOTIFY_MOTION or self.last_mouse_user is None or self.last_mouse_user != ss.uuid:
                if hasattr(ss, "update_mouse"):
                    ss.update_mouse(wid, event.x_root, event.y_root, event.x, event.y)

    def get_pointer_device(self, deviceid: int):
        # pointerlog("get_pointer_device(%i) input_devices_data=%s", deviceid, self.input_devices_data)
        if self.input_devices_data:
            device_data = self.input_devices_data.get(deviceid)
            if device_data:
                pointerlog("get_pointer_device(%i) device=%s", deviceid, device_data.get("name"))
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
                pointerlog("_get_pointer_abs_coordinates(%i, %s)=%s window geometry=%s", wid, pos, (x, y), geom)
        return x, y

    def _move_pointer(self, device_id: int, wid: int, pos, props=None) -> None:
        # (this is called within a `xswallow` context)
        x, y = self._get_pointer_abs_coordinates(wid, pos)
        self.device_move_pointer(device_id, wid, (x, y), props)

    def device_move_pointer(self, device_id: int, wid: int, pos, props: dict):
        device = self.get_pointer_device(device_id)
        x, y = pos
        pointerlog("move_pointer(%s, %s, %s) device=%s, position=%s", wid, pos, device_id, device, (x, y))
        try:
            device.move_pointer(x, y, props)
        except Exception as e:
            pointerlog.error("Error: failed to move the pointer to %sx%s using %s", x, y, device)
            pointerlog.estr(e)

    def do_process_mouse_common(self, proto, device_id: int, wid: int, pointer, props) -> bool:
        pointerlog("do_process_mouse_common%s", (proto, device_id, wid, pointer, props))
        if self.readonly:
            return False
        with xsync:
            from xpra.x11.bindings.keyboard import X11KeyboardBindings
            pos = X11KeyboardBindings().query_pointer()
        if (pointer and pos != pointer[:2]) or self.input_devices == "xi":
            with xswallow:
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
                ss.user_event()

    def do_process_button_action(self, proto, device_id: int, wid: int, button: int, pressed: bool,
                                 pointer, props: dict) -> None:
        if "modifiers" in props:
            self._update_modifiers(proto, wid, props.get("modifiers"))
        props = {}
        if self.process_mouse_common(proto, device_id, wid, pointer, props):
            self.button_action(device_id, wid, pointer, button, pressed, props)

    def button_action(self, device_id: int, wid: int, pointer, button: int, pressed: bool, props: dict) -> None:
        device = self.get_pointer_device(device_id)
        assert device, "pointer device %s not found" % device_id
        if button in (4, 5) and wid:
            self.record_wheel_event(wid, button)
        try:
            pointerlog("%s%s", device.click, (button, pressed, props))
            with xsync:
                device.click(button, pressed, props)
        except XError:
            pointerlog("button_action%s", (device_id, wid, pointer, button, pressed, props), exc_info=True)
            pointerlog.error("Error: failed (un)press mouse button %s", button)
