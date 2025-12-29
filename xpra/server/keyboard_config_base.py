# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from typing import Any

from xpra.util.objects import typedict


class KeyboardConfigBase:
    """ Base class representing the keyboard configuration for a server.
    """
    __slots__ = ("enabled", "owner", "sync", "pressed_translation")

    def __init__(self):
        self.enabled = True
        self.owner = None
        self.sync = True
        self.pressed_translation: dict[int, tuple[int, int]] = {}

    def __repr__(self):
        return "KeyboardConfigBase"

    def get_info(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "owner": self.owner or "",
            "sync": self.sync,
        }

    def parse_options(self, props: typedict) -> int:
        oldsync = self.sync
        keymap_dict = typedict(props.dictget("keymap") or {})
        self.sync = keymap_dict.boolget("sync", True)
        return int(oldsync != self.sync)

    def get_hash(self) -> str:
        return ""

    def set_layout(self, layout, variant, options) -> bool:
        """ should be overridden to configure the keyboard layout """
        return False

    def set_keymap(self, translate_only=False) -> None:
        """ should be overridden to configure the keymap """

    def set_default_keymap(self) -> None:
        """ should be overridden to set a default keymap """

    def make_keymask_match(self, modifier_list, ignored_modifier_keycode=0, ignored_modifier_keynames=None) -> None:
        """ should be overridden to match the modifier state specified """

    def get_keycode(self, client_keycode: int, keyname: str, pressed: bool,
                    modifiers: list[str], keyval: int, keystr: str, group: int) -> tuple[int, int]:
        if not keyname and client_keycode < 0:
            return -1, group
        if not pressed:
            r = self.pressed_translation.get(client_keycode)
            if r:
                # del self.pressed_translation[client_keycode]
                return r
        keycode, group = self.do_get_keycode(client_keycode, keyname, pressed, modifiers, keyval, keystr, group)
        if keycode < 0 and not keyname.islower():
            keyname = keyname.lower()
            keycode, group = self.do_get_keycode(client_keycode, keyname, pressed, modifiers, keyval, keystr, group)
        if pressed and keycode > 0:
            # keep track of it, so we can unpress the same key:
            self.pressed_translation[client_keycode] = keycode, group
        return keycode, group

    def do_get_keycode(self, client_keycode: int, keyname: str, pressed: bool,
                       modifiers: list[str], keyval: int, keystr: str, group: int) -> tuple[int, int]:
        from xpra.log import Logger  # pylint: disable=import-outside-toplevel
        log = Logger("keyboard")
        log("do_get_keycode%s", (client_keycode, keyname, pressed, modifiers, keyval, keystr, group))
        log.warn("Warning: %s does not implement get_keycode!", type(self))
        return -1, 0

    def is_modifier(self, _keycode: int) -> bool:
        # should be overridden in subclasses
        return False
