# This file is part of Xpra.
# Copyright (C) 2025 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.


from xpra.server.keyboard_config_base import KeyboardConfigBase


class KeyboardConfig(KeyboardConfigBase):

    def do_get_keycode(self, client_keycode: int, keyname: str, pressed: bool,
                       modifiers, keyval: int, keystr: str, group: int) -> tuple[int, int]:
        return client_keycode, group
