# This file is part of Xpra.
# Copyright (C) 2018 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.util.objects import typedict
from xpra.server.subsystem.keyboard import KeyboardServer
from xpra.x11.error import xsync
from xpra.log import Logger

log = Logger("x11", "server", "keyboard")


class X11KeyboardServer(KeyboardServer):

    def __init__(self):
        KeyboardServer.__init__(self)
        self.readonly = False

    def get_keyboard_config(self, props=None):
        p = typedict(props or {})
        from xpra.x11.server.keyboard_config import KeyboardConfig
        keyboard_config = KeyboardConfig()
        keyboard_config.enabled = p.boolget("keyboard", True)
        keyboard_config.parse_options(p)
        keyboard_config.parse_layout(p)
        log("get_keyboard_config(..)=%s", keyboard_config)
        return keyboard_config

    def set_keymap(self, server_source, force=False) -> None:
        if self.readonly:
            return

        def reenable_keymap_changes(*args) -> bool:
            log("reenable_keymap_changes(%s)", args)
            self.keymap_changing_timer = 0
            self._keys_changed()
            return False

        # prevent _keys_changed() from firing:
        # (using a flag instead of keymap.disconnect(handler) as this did not seem to work!)
        if not self.keymap_changing_timer:
            # use idle_add to give all the pending
            # events a chance to run first (and get ignored)
            from xpra.os_util import gi_import
            GLib = gi_import("GLib")
            self.keymap_changing_timer = GLib.timeout_add(100, reenable_keymap_changes)
        # if sharing, don't set the keymap, translate the existing one:
        other_ui_clients = [s.uuid for s in self._server_sources.values() if s != server_source and s.ui_client]
        translate_only = len(other_ui_clients) > 0
        log("set_keymap(%s, %s) translate_only=%s", server_source, force, translate_only)
        with xsync:
            # pylint: disable=access-member-before-definition
            server_source.set_keymap(self.keyboard_config, self.keys_pressed, force, translate_only)
            self.keyboard_config = server_source.keyboard_config
