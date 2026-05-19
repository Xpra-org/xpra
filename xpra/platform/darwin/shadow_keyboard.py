# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.platform.darwin.keyboard_config import KeyboardConfig
from xpra.server.shadow.keyboard import ShadowKeyboardManager


class DarwinShadowKeyboardManager(ShadowKeyboardManager):
    """
    macOS keyboard subsystem for shadow servers.
    """

    @staticmethod
    def get_keyboard_config(_props=None) -> KeyboardConfig:
        return KeyboardConfig()
