# This file is part of Xpra.
# Copyright (C) 2010 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2011 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from typing import Any
from collections.abc import Callable, Sequence

from xpra.keyboard.common import KeyEvent
from xpra.keyboard.mask import mask_to_names, MODIFIER_MAP
from xpra.log import Logger

log = Logger("keyboard")


class KeyboardBase:

    def __init__(self):
        self.init_vars()

    def init_vars(self) -> None:
        self.modifier_keys: dict[str, str] = {}
        self.modifier_names: dict[str, str] = {}
        self.modifier_keycodes: dict[str, list[int]] = {}
        self.modifier_mappings: dict[str, Any] = {}
        # FIXME: this only allows a single modifier per mask
        # and in some cases we want to allow other modifier names
        # to use the same mask... (ie: META on OSX)
        self.modifier_map = MODIFIER_MAP

    def cleanup(self) -> None:
        self.init_vars()

    def has_bell(self) -> bool:
        return False

    def _add_modifier_mapping(self, a, b, modifier) -> None:
        # log.info("%s (%s), %s (%s)", keycode, type(keycode), keyname, type(keyname))
        if isinstance(a, int) and isinstance(b, (bytes, str)):
            self._do_add_modifier_mapping((b,), a, modifier)
        elif isinstance(a, (str, bytes)) and isinstance(b, int):
            # level = b
            self._do_add_modifier_mapping((a,), 0, modifier)
        elif isinstance(a, (bytes, str)) and isinstance(b, (bytes, str)):
            self._do_add_modifier_mapping((a, b), 0, modifier)
        elif isinstance(a, (tuple, list)) and isinstance(b, (bytes, str)):
            # ie: a=(57, 'CapsLock'), b='CapsLock'
            if len(a) == 2:
                self._add_modifier_mapping(a[0], a[1], modifier)
            self._add_modifier_mapping((b,), 0, modifier)
        elif isinstance(a, (tuple, list)) and isinstance(b, int):
            # ie: a=('CapsLock'), b=0
            self._do_add_modifier_mapping(a, 0, modifier)
        else:
            log.warn(f"Warning: unexpected key definition: {type(a)}, {type(b)}")
            log.warn(f" values: {a}, {b}")

    def _do_add_modifier_mapping(self, keynames, keycode, modifier) -> None:
        for keyname in keynames:
            self.modifier_keys[keyname] = modifier
            self.modifier_names[modifier] = keyname
            if keycode:
                keycodes = self.modifier_keycodes.setdefault(keyname, [])
                if keycode not in keycodes:
                    keycodes.append(keycode)

    def set_modifier_mappings(self, mappings: dict[str, Any]) -> None:
        log("set_modifier_mappings({mappings})")
        self.modifier_mappings = mappings
        self.modifier_keys = {}
        self.modifier_names = {}
        self.modifier_keycodes = {}
        for modifier, keys in mappings.items():
            for a, b in keys:
                self._add_modifier_mapping(a, b, modifier)
        log(f"modifier_keys={self.modifier_keys}")
        log(f"modifier_names={self.modifier_names}")
        log(f"modifier_keycodes={self.modifier_keycodes}")

    def mask_to_names(self, mask) -> list[str]:
        # mask can be an int, or a `ModifierType` enum:
        return mask_to_names(int(mask), self.modifier_map)

    def get_keymap_modifiers(self) -> tuple[dict, list[str], list[str]]:
        """
            ask the server to manage capslock ('lock') which can be missing from mouse events
            (or maybe this is virtualbox causing it?)
        """
        return {}, [], ["lock"]

    def get_keymap_spec(self) -> dict[str, Any]:
        return {}

    def get_x11_keymap(self) -> dict[int, list[str]]:
        return {}

    def get_layout_spec(self) -> tuple[str, str, Sequence[str], str, Sequence[str], str]:
        return "", "", (), "", (), ""

    def get_keyboard_repeat(self) -> tuple[int, int] | None:
        return None

    def update_modifier_map(self, mod_meanings) -> None:
        log(f"update_modifier_map({mod_meanings})")
        self.modifier_map = MODIFIER_MAP

    def process_key_event(self, send_key_action_cb: Callable, wid: int, key_event: KeyEvent):
        # default is to just send it as-is:
        send_key_action_cb(wid, key_event)
