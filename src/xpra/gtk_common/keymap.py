#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2011-2013 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.util import nn
from xpra.log import Logger
log = Logger("keyboard")


def get_gtk_keymap(ignore_keys=[None, "VoidSymbol"]):
    """
        Augment the keymap we get from gtk.gdk.keymap_get_default()
        by adding the keyval_name.
        We can also ignore some keys
    """
    from xpra.gtk_common.gtk_util import get_default_keymap, import_gdk, is_gtk3
    gdk = import_gdk()
    keymap = get_default_keymap()
    keycodes=[]
    for i in range(0, 2**8):
        entries = keymap.get_entries_for_keycode(i)
        log("%s.get_entries_for_keycode(%s)=%s", keymap, i, entries)
        if not entries:
            continue
        if is_gtk3():
            found, keys, keyvals = entries
            if not found:
                continue
            for i in range(len(keys)):
                key = keys[i]
                keyval = keyvals[i]
                name = gdk.keyval_name(keyval)
                keycodes.append((nn(keyval), nn(name), nn(key.keycode), nn(key.group), nn(key.level)))
        else:
            #gtk2:
            for keyval, keycode, group, level in entries:
                #assert keycode==i
                name = gdk.keyval_name(keyval)
                if name not in ignore_keys:
                    keycodes.append((nn(keyval), nn(name), nn(keycode), nn(group), nn(level)))
    log("get_gtk_keymap(%s)=%s (keymap=%s)", ignore_keys, keycodes, keymap)
    return keycodes


def main():
    import sys
    from xpra.platform import init, clean
    try:
        init("Keymap-Tool", "Keymap Information Tool")
        if "-v" in sys.argv:
            log.enable_debug()
        gtk_keymap = get_gtk_keymap()
        def pkey(*entries):
            print("".join([str(x).ljust(18) for x in entries]))
        pkey("keyval", "name", "keycode", "group", "level")
        for x in gtk_keymap:
            pkey(*x)
    finally:
        clean()


if __name__ == "__main__":
    main()
