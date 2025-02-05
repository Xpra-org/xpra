#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2011 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from collections.abc import Sequence

from xpra.util.str_fn import Ellipsizer
from xpra.os_util import gi_import
from xpra.log import Logger

log = Logger("keyboard")
verboselog = Logger("keyboard", "verbose")

# this allows platforms to inject keyname workarounds
# the key is a tuple (keyname, keyval, keycode)
# the value is the keyname override
KEY_TRANSLATIONS: dict[tuple[str, int, int], str] = {}


def get_default_keymap():
    Gdk = gi_import("Gdk")
    display = Gdk.Display.get_default()
    if not display:
        return Gdk.Keymap.get_default()
    return Gdk.Keymap.get_for_display(display)


def get_gtk_keymap(ignore_keys=("", "VoidSymbol", "0xffffff")) -> Sequence[tuple[int, str, int, int, int]]:
    """
        Augment the keymap we get from gtk.gdk.keymap_get_default()
        by adding the keyval_name.
        We can also ignore some keys
    """
    Gdk = gi_import("Gdk")
    keymap = get_default_keymap()
    if not keymap:
        return ()
    log("get_default_keymap(%s)=%s, direction=%s, bidirectional layouts: %s",
        ignore_keys, keymap, keymap.get_direction(), keymap.have_bidi_layouts())
    keycodes: list[tuple[int, str, int, int, int]] = []
    for i in range(0, 2 ** 8):
        entries = keymap.get_entries_for_keycode(i)
        if not entries:  # pragma: no cover
            continue
        found, keys, keyvals = entries
        if not found:
            verboselog("keycode %3i: ()", i)
            continue
        added = []
        for j, key in enumerate(keys):
            keyval = keyvals[j]
            keycode = key.keycode
            name = Gdk.keyval_name(keyval) or ""
            name = KEY_TRANSLATIONS.get((name, keyval, keycode), name)
            group = key.group or 0
            if name not in ignore_keys:
                kdef = keyval or 0, name or "", keycode or 0, group, key.level or 0
                keycodes.append(kdef)
                added.append(kdef)
        verboselog("keycode %3i: %s", i, added)
    log("get_gtk_keymap(%s)=%s (keymap=%s)", ignore_keys, Ellipsizer(keycodes), Ellipsizer(keymap))
    verboselog("get_gtk_keymap(%s)=%s (keymap=%s)", ignore_keys, keycodes, keymap)
    return tuple(keycodes)


def main() -> int:  # pragma: no cover
    # pylint: disable=import-outside-toplevel
    import sys
    from xpra.platform import program_context
    from xpra.log import enable_color, consume_verbose_argv
    with program_context("Keymap-Tool", "Keymap Information Tool"):
        enable_color()
        consume_verbose_argv(sys.argv, "keyboard")
        gtk_keymap = get_gtk_keymap()
        sizes = [16, 28, 8, 8, 8]

        def pkey(*entries) -> None:
            print(("".join([str(x).ljust(sizes[i]) for i, x in enumerate(entries)])).strip())

        pkey("keyval", "name", "keycode", "group", "level")
        for x in gtk_keymap:
            pkey(*x)
    return 0


if __name__ == "__main__":  # pragma: no cover
    main()
