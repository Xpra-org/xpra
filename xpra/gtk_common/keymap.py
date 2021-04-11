#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2011-2017 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.log import Logger

log = Logger("keyboard")

#this allows platforms to inject keyname workarounds
# the key is a tuple (keyname, keyval, keycode)
# the value is the keyname override
KEY_TRANSLATIONS = {}


def get_gtk_keymap(ignore_keys=(None, "VoidSymbol", "0xffffff")):
    """
        Augment the keymap we get from gtk.gdk.keymap_get_default()
        by adding the keyval_name.
        We can also ignore some keys
    """
    from xpra.gtk_common.gtk_util import keymap_get_for_display, display_get_default, import_gdk, is_gtk3
    gdk = import_gdk()
    display = display_get_default()
    if not display:
        return ()
    keymap = keymap_get_for_display(display)
    log("keymap_get_for_display(%s)=%s, direction=%s, bidirectional layouts: %s",
        display, keymap, keymap.get_direction(), keymap.have_bidi_layouts())
    keycodes=[]
    for i in range(0, 2**8):
        entries = keymap.get_entries_for_keycode(i)
        log("get_entries_for_keycode(%s)=%s", i, entries)
        if not entries:
            continue
        if is_gtk3():
            found, keys, keyvals = entries
            if not found:
                continue
            for j, key in enumerate(keys):
                keyval = keyvals[j]
                keycode = key.keycode
                name = gdk.keyval_name(keyval)
                name = KEY_TRANSLATIONS.get((name, keyval, keycode), name)
                group = key.group or 0
                if name not in ignore_keys:
                    keycodes.append((keyval or 0, name or "", keycode or 0, group, key.level or 0))
        else:
            #gtk2:
            for keyval, keycode, group, level in entries:
                #assert keycode==i
                name = gdk.keyval_name(keyval)
                name = KEY_TRANSLATIONS.get((name, keyval, keycode), name)
                if name not in ignore_keys:
                    keycodes.append((keyval or 0, name or "", keycode or 0, group or 0, level or 0))
    log("get_gtk_keymap(%s)=%s (keymap=%s)", ignore_keys, keycodes, keymap)
    return keycodes


def main():
    import sys
    from xpra.platform import program_context
    from xpra.log import enable_color
    with program_context("Keymap-Tool", "Keymap Information Tool"):
        enable_color()
        if "-v" in sys.argv or "--verbose" in sys.argv:
            log.enable_debug()
        gtk_keymap = get_gtk_keymap()
        sizes = [16, 28, 8, 8, 8]
        def pkey(*entries):
            print(("".join([str(x).ljust(sizes[i]) for i,x in enumerate(entries)])).strip())
        pkey("keyval", "name", "keycode", "group", "level")
        for x in gtk_keymap:
            pkey(*x)
    return 0


if __name__ == "__main__":
    main()
