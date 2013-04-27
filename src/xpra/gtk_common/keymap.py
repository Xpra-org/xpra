#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2011-2013 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

def nn(x):
    if x is None:
        return ""
    return x

def get_gtk_keymap(ignore_keys=[None, "VoidSymbol"]):
    """
        Augment the keymap we get from gtk.gdk.keymap_get_default()
        by adding the keyval_name.
        We can also ignore some keys
    """
    from xpra.gobject_compat import import_gdk
    gdk = import_gdk()
    try:
        keymap = gdk.keymap_get_default()
    except:
        keymap = None
        return  []
    keycodes=[]
    used_keycodes = []
    max_entries = 1
    for i in range(0, 2**8):
        entries = keymap.get_entries_for_keycode(i)
        if entries:
            max_entries = max(max_entries, len(entries))
            for keyval, keycode, group, level in entries:
                name = gdk.keyval_name(keyval)
                if name not in ignore_keys:
                    keycodes.append((nn(keyval), nn(name), nn(keycode), nn(group), nn(level)))
                    used_keycodes.append(keycode)
    return keycodes


def main():
    gtk_keymap = get_gtk_keymap()
    print("gtk_keymap: (keyval, name, keycode, group, level)\n%s" % ("\n".join([str(x) for x in gtk_keymap])))


if __name__ == "__main__":
    main()
