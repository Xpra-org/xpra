# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.server.shadow.keyboard import ShadowKeyboardMixin
from xpra.x11.subsystem.keyboard import X11KeyboardManager


class X11ShadowKeyboardManager(ShadowKeyboardMixin, X11KeyboardManager):
    """
    X11 keyboard subsystem for shadow servers.
    """

    def __init__(self, server=None):
        super().__init__(server)
        self.modify_keymap = False

    def init(self, opts) -> None:
        super().init(opts)
        self.modify_keymap = opts.keyboard_layout.lower() in ("client", "auto")

    def set_keymap(self, server_source, force=False) -> None:
        if server_source and getattr(server_source, "effective_readonly", lambda: self.server.readonly)():
            return
        if self.modify_keymap:
            X11KeyboardManager.set_keymap(self, server_source, force)
        else:
            ShadowKeyboardMixin.set_keymap(self, server_source, force)
