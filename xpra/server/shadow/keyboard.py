# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.server.subsystem.keyboard import KeyboardManager
from xpra.log import Logger

log = Logger("shadow")


class ShadowKeyboardMixin:
    def _keys_changed(self) -> None:
        super()._keys_changed()
        from xpra.platform.keyboard import Keyboard
        log.info("the keymap has been changed: %s", Keyboard().get_layout_spec()[0])

    def set_keyboard_repeat(self, *_args) -> None:
        """ don't override the existing desktop """

    def set_keymap(self, server_source, force=False) -> None:
        log("set_keymap%s", (server_source, force))
        log.info("shadow server: setting default keymap translation")
        self.set_current_config(server_source.set_default_keymap())


class ShadowKeyboardManager(ShadowKeyboardMixin, KeyboardManager):
    """
    Keyboard subsystem for shadow servers.
    """
