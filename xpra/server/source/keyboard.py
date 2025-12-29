# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from typing import Any

from xpra.common import BACKWARDS_COMPATIBLE
from xpra.util.str_fn import Ellipsizer
from xpra.server.source.stub import StubClientConnection
from xpra.keyboard.mask import DEFAULT_MODIFIER_MEANINGS
from xpra.util.objects import typedict
from xpra.log import Logger

log = Logger("keyboard")
ibuslog = Logger("ibus")


class KeyboardConnection(StubClientConnection):
    """
    Manage keyboard input
    """

    @classmethod
    def is_needed(cls, caps: typedict) -> bool:
        if caps.boolget("keyboard"):
            return True
        if BACKWARDS_COMPATIBLE:
            return bool(caps.get("xkbmap_keycodes"))  # legacy clients
        return False

    def init_state(self) -> None:
        self.keyboard_config = None
        self.ibus = False

    def cleanup(self) -> None:
        self.keyboard_config = None

    def parse_client_caps(self, c: typedict) -> None:
        self.ibus = c.boolget("ibus")
        ibuslog(f"client ibus support: {self.ibus}")

    def get_info(self) -> dict[str, Any]:
        info: dict[str, Any] = {}
        kc = self.keyboard_config
        if kc:
            info["keyboard"] = kc.get_info()
        return info

    def get_caps(self) -> dict[str, Any]:
        caps: dict[str, Any] = {}
        # expose the "modifier_client_keycodes" defined in the X11 server keyboard config object,
        # so clients can figure out which modifiers map to which keys:
        mck = getattr(self.keyboard_config, "modifier_client_keycodes", None)
        if mck:
            caps["modifier_keycodes"] = mck
        modifiers = getattr(self.keyboard_config, "keynames_for_mod", {})
        if modifiers:
            caps["modifiers-keynames"] = modifiers
        return caps

    def send_ibus_layouts(self, ibus_layouts: dict) -> None:
        ibuslog(f"send_ibus_layouts(%s) {self.ibus=}", Ellipsizer(ibus_layouts))
        if self.ibus and ibus_layouts:
            self.send_setting_change("ibus-layouts", ibus_layouts)

    def set_layout(self, layout: str, variant: str, options) -> bool:
        if not self.keyboard_config:
            return False
        return self.keyboard_config.set_layout(layout, variant, options)

    def keys_changed(self) -> None:
        kc = self.keyboard_config
        if kc:
            kc.compute_modifier_map()
            kc.compute_modifier_keynames()
        log("keys_changed() updated keyboard config=%s", self.keyboard_config)

    def make_keymask_match(self, modifier_list, ignored_modifier_keycode=0, ignored_modifier_keynames=None):
        kc = self.keyboard_config
        if kc and kc.enabled:
            kc.make_keymask_match(modifier_list, ignored_modifier_keycode, ignored_modifier_keynames)

    def set_default_keymap(self):
        log("set_default_keymap() keyboard_config=%s", self.keyboard_config)
        kc = self.keyboard_config
        if kc:
            kc.set_default_keymap()
        return kc

    def is_modifier(self, keyname: str, keycode: int) -> bool:
        if keyname in DEFAULT_MODIFIER_MEANINGS:
            return True
        # keyboard config should always exist if we are here?
        kc = self.keyboard_config
        if kc:
            return kc.is_modifier(keycode)
        return False

    def set_keymap(self, current_keyboard_config, keys_pressed, force: bool = False,
                   translate_only: bool = False) -> None:
        kc = self.keyboard_config
        log("set_keymap%s keyboard_config=%s", (current_keyboard_config, keys_pressed, force, translate_only), kc)
        if kc and kc.enabled:
            current_id = ""
            if current_keyboard_config and current_keyboard_config.enabled:
                current_id = current_keyboard_config.get_hash()
            keymap_id = kc.get_hash()
            log("current keyboard id=%s, new keyboard id=%s", current_id, keymap_id)
            if force or not current_id or keymap_id != current_id:
                kc.keys_pressed = keys_pressed
                kc.set_keymap(translate_only)
                kc.owner = self.uuid
            else:
                log.info("keyboard mapping already configured (skipped)")
                self.keyboard_config = current_keyboard_config

    def get_keycode(self, client_keycode: int, keyname: str, pressed: bool,
                    modifiers: list[str], keyval, keystr: str, group: int) -> tuple[int, int]:
        kc = self.keyboard_config
        if kc is None:
            log.info("ignoring client key %s / %s since keyboard is not configured", client_keycode, keyname)
            return -1, 0
        return kc.get_keycode(client_keycode, keyname, pressed, modifiers, keyval, keystr, group)
