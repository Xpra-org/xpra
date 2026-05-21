# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.server.subsystem.keyboard import KeyboardManager
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
