#!/usr/bin/env python
# This file is part of Parti.
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2011, 2012 Antoine Martin <antoine@nagafix.co.uk>
# Parti is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

def mask_to_names(mask, modifier_map):
    modifiers = []
    for modifier in DEFAULT_ALL_MODIFIER_NAMES:
        modifier_mask = modifier_map.get(modifier)
        if (modifier_mask is not None) and (modifier_mask & mask):
            modifiers.append(modifier)
            mask &= ~modifier_mask
    return modifiers

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
    from wimpiggy.gobject_compat import import_gdk
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



DEFAULT_MODIFIER_IGNORE_KEYNAMES = ["Caps_Lock", "Num_Lock", "Scroll_Lock"]

ALL_X11_MODIFIERS = {
                    "shift"     : 0,
                    "lock"      : 1,
                    "control"   : 2,
                    "mod1"      : 3,
                    "mod2"      : 4,
                    "mod3"      : 5,
                    "mod4"      : 6,
                    "mod5"      : 7
                    }

DEFAULT_MODIFIER_NAMES = ["shift", "control", "meta", "super", "hyper", "alt"]
DEFAULT_MODIFIER_NUISANCE = ["lock", "num", "scroll"]
DEFAULT_ALL_MODIFIER_NAMES = DEFAULT_MODIFIER_NAMES+DEFAULT_MODIFIER_NUISANCE+["mod1", "mod2", "mod3", "mod4", "mod5"]

DEFAULT_MODIFIER_MEANINGS = {
        "Shift_L"   : "shift",
        "Shift_R"   : "shift",
        "Caps_Lock" : "lock",
        "Control_L" : "control",
        "Control_R" : "control",
        "Alt_L"     : "mod1",
        "Alt_R"     : "mod1",
        "Meta_L"    : "mod1",
        "Meta_R"    : "mod1",
        "Num_Lock"  : "mod2",
        "Super_L"   : "mod3",
        "Super_R"   : "mod3",
        "Hyper_L"   : "mod4",
        "Hyper_R"   : "mod4",
        "ISO_Level3_Shift"  : "mod5",
        "Mode_switch"       : "mod5",
        }
