# This file is part of Xpra.
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2012 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.os_util import gi_import
from xpra.gtk.keymap import get_default_keymap
from xpra.x11.bindings.keyboard import X11KeyboardBindings
from xpra.keyboard.mask import DEFAULT_MODIFIER_MEANINGS, MODIFIER_MAP

X11Keyboard = X11KeyboardBindings()

Gdk = gi_import("Gdk")


def grok_modifier_map(meanings) -> dict[str, int]:
    """Return a dict mapping modifier names to corresponding X modifier
    bitmasks."""
    # is this still correct for GTK3?
    modifier_map = MODIFIER_MAP.copy()
    modifier_map |= {
        "scroll": 0,
        "num": 0,
        "meta": 0,
        "super": 0,
        "hyper": 0,
        "alt": 0,
    }
    if not meanings:
        meanings = DEFAULT_MODIFIER_MEANINGS

    max_keypermod, keycodes = X11Keyboard.get_modifier_map()
    assert len(keycodes) == 8 * max_keypermod
    keymap = get_default_keymap()
    for i in range(8):
        for j in range(max_keypermod):
            keycode = keycodes[i * max_keypermod + j]
            if keycode:
                entries = keymap.get_entries_for_keycode(keycode)
                if entries is None:  # pragma: no cover
                    # This keycode has no entry in the keymap:
                    continue
                found, _, keyvals = entries
                if not found:  # pragma: no cover
                    continue
                for keyval in keyvals:
                    keyval_name = Gdk.keyval_name(keyval)
                    modifier = meanings.get(keyval_name)
                    if modifier:
                        modifier_map[modifier] |= (1 << i)
    return modifier_map
