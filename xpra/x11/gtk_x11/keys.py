# This file is part of Xpra.
# Copyright (C) 2008, 2009 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2012-2019 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from gi.repository import Gdk

from xpra.x11.bindings.keyboard_bindings import X11KeyboardBindings #@UnresolvedImport
from xpra.keyboard.mask import DEFAULT_MODIFIER_MEANINGS

X11Keyboard = X11KeyboardBindings()


def grok_modifier_map(display, meanings):
    """Return an dict mapping modifier names to corresponding X modifier
    bitmasks."""
    #TODO: needs fixing for GTK3
    from xpra.keyboard.mask import MODIFIER_MAP
    modifier_map = MODIFIER_MAP.copy()
    modifier_map.update({
        "scroll":   0,
        "num":      0,
        "meta":     0,
        "super":    0,
        "hyper":    0,
        "alt":      0,
        })
    if not meanings:
        meanings = DEFAULT_MODIFIER_MEANINGS

    (max_keypermod, keycodes) = X11Keyboard.get_modifier_map()
    assert len(keycodes) == 8 * max_keypermod
    keymap = Gdk.Keymap.get_for_display(display)
    for i in range(8):
        for j in range(max_keypermod):
            keycode = keycodes[i * max_keypermod + j]
            if keycode:
                entries = keymap.get_entries_for_keycode(keycode)
                if entries is None:     # pragma: no cover
                    # This keycode has no entry in the keymap:
                    continue
                found, _, keyvals = entries
                if not found:           # pragma: no cover
                    continue
                for keyval in keyvals:
                    keyval_name = Gdk.keyval_name(keyval)
                    modifier = meanings.get(keyval_name)
                    if modifier:
                        modifier_map[modifier] |= (1 << i)
    return modifier_map
