# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.platform.win32.keyboard_config import KeyboardConfig
from xpra.server.shadow.keyboard import ShadowKeyboardManager
from xpra.util.objects import typedict


class Win32ShadowKeyboardManager(ShadowKeyboardManager):
    """
    Win32 keyboard subsystem for shadow servers.
    """

    def get_keyboard_config(self, _props=None) -> KeyboardConfig:
        return KeyboardConfig()

    def do_process_keyboard_event(self, proto, wid: int, keyname: str, pressed: bool, attrs: dict) -> None:
        vk_code = typedict(attrs).intget("vk-code", 0)
        if vk_code:
            pass  # todo!
        super().do_process_keyboard_event(proto, wid, keyname, pressed, attrs)
