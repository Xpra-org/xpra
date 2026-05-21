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

    def make_keyboard_device(self):
        return self.server.compositor.get_keyboard_device()

    def get_keyboard_config(self, props=None):
        from xpra.wayland.keyboard_config import KeyboardConfig
        keyboard_config = KeyboardConfig()
        log("get_keyboard_config(%s)=%s", props, keyboard_config)
        return keyboard_config

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
