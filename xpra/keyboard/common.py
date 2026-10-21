# This file is part of Xpra.
# Copyright (C) 2024 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.util.objects import typedict
from xpra.util.str_fn import csv
from xpra.util.env import envbool
from xpra.log import Logger

DELAY_KEYBOARD_DATA = envbool("XPRA_DELAY_KEYBOARD_DATA", True)
# the xkb names are short ascii strings, ie: "us,fr", "grp:alt_shift_toggle,ctrl:nocaps"
MAX_KEYMAP_STRING = 256
MAX_KEYMAP_LAYOUTS = 32

# this allows platforms to inject keyname workarounds
# the key is a tuple (keyname, keyval, keycode)
# the value is the keyname override
# (this lives here rather than in `xpra.gtk.keymap` so that
# toolkit-free clients - ie: win32 - can populate it without importing any gtk bits)
KEY_TRANSLATIONS: dict[tuple[str, int, int], str] = {}


def keymap_str(d: typedict, key: str, default: str = "") -> str:
    """
    The xkb layout, variant, options, model or rules received from a client.
    Invalid values are replaced with the default.
    """
    return valid_keymap_str(key, d.strget(key, default), default)


def valid_keymap_str(key: str, value: str, default: str = "") -> str:
    if len(value) > MAX_KEYMAP_STRING or not (value.isascii() and value.isprintable()):
        log = Logger("keyboard")
        log.warn(f"Warning: ignoring invalid keyboard {key} {value[:32]!r}")
        return default
    return value


def keymap_strtuple(d: typedict, key: str) -> tuple[str, ...]:
    """
    The xkb layouts or variants received from a client.
    Invalid values are replaced with empty strings
    so that layouts and variants still match by position.
    """
    values = d.strtupleget(key)
    if len(values) > MAX_KEYMAP_LAYOUTS:
        log = Logger("keyboard")
        log.warn(f"Warning: too many keyboard {key}, only using the first {MAX_KEYMAP_LAYOUTS} out of {len(values)}")
        values = values[:MAX_KEYMAP_LAYOUTS]
    return tuple(valid_keymap_str(key, value) for value in values)


class KeyEvent:
    __slots__ = ("modifiers", "keyname", "keyval", "keycode", "group", "string", "pressed")

    def __init__(self):
        self.modifiers: list[str] = []
        self.keyname: str = ""
        self.keyval: int = 0
        self.keycode: int = 0
        self.group: int = 0
        self.string: str = ""
        self.pressed: bool = True

    def __repr__(self):
        strattrs = csv(f"{k}="+repr(getattr(self, k)) for k in KeyEvent.__slots__)
        return f"KeyEvent({strattrs})"
