# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from collections.abc import Sequence

from xpra.server.subsystem.keyboard import KeyboardManager
from xpra.util.objects import typedict
from xpra.log import Logger

log = Logger("server", "wayland")


class WaylandKeyboardManager(KeyboardManager):
    BACKEND = "wayland"

    def make_keyboard_device(self):
        return self.server.compositor.get_keyboard_device()

    def get_keyboard_config(self, props=None):
        from xpra.wayland.keyboard_config import KeyboardConfig
        keyboard_config = KeyboardConfig()
        log("get_keyboard_config(%s)=%s", props, keyboard_config)
        return keyboard_config

    def get_keycode(self, ss, client_keycode: int, keyname: str,
                    pressed: bool, modifiers: list, keyval: int, keystr: str, group: int):
        # The Wayland virtual keyboard uses its own xkb keymap, so the client's keycode
        # (from a foreign keymap, e.g. Win32 VK codes) is not meaningful here.
        # The xkb keymap uses X11-style keycodes (evdev + 8) and `press_key` subtracts 8
        # before handing them to wlroots, so we just return what the keymap gives us.
        keycode = -1
        if self.device:
            if keyval > 0:
                keycode = self.device.get_keycode_for_keysym(keyval)
            if keycode < 0 and keyname:
                keycode = self.device.get_keycode_for_keyname(keyname)
        if keycode > 0:
            log("get_keycode: keyname=%r keyval=%i client_keycode=%i -> xkb keycode=%i",
                keyname, keyval, client_keycode, keycode)
            return keycode, group
        log("get_keycode: no xkb mapping for keyname=%r keyval=%i, falling back",
            keyname, keyval)
        return super().get_keycode(ss, client_keycode, keyname, pressed, modifiers, keyval, keystr, group)

    def fake_key(self, keycode: int, press: bool) -> None:
        log("fake_key(%i, %s)", keycode, press)
        if self.device:
            self.device.reapply_modifiers()
        super().fake_key(keycode, press)
        self.server.compositor.flush()

    def update_keyboard_modifiers(self, modifiers: Sequence[str], group: int = -1) -> None:
        if group < 0 and self.device:
            group = self.device.get_layout_group()
        if self.device:
            self.device.update_modifiers(modifiers, group)

    def do_process_keyboard_event(self, proto, wid: int, keyname: str, pressed: bool, kattrs: dict) -> None:
        attrs = typedict(kattrs)
        if "modifiers" in kattrs:
            self.update_keyboard_modifiers(attrs.strtupleget("modifiers", ()), attrs.intget("group", 0))
        super().do_process_keyboard_event(proto, wid, keyname, pressed, kattrs)

    def set_keyboard_layout_group(self, grp: int) -> None:
        if self.device:
            self.device.set_layout_group(grp)
