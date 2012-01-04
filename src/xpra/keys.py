# This file is part of Parti.
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2011, 2012 Antoine Martin <antoine@nagafix.co.uk>
# Parti is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

def mask_to_names(mask, modifier_map, modifier_names):
    modifiers = []
    for modifier in modifier_names:
        modifier_mask = modifier_map[modifier]
        if modifier_mask & mask:
            modifiers.append(modifier)
            mask &= ~modifier_mask
    return modifiers

def get_modifiers_ignored(xkbmap_mod_meanings):
    mod_ignore = DEFAULT_MODIFIER_NUISANCE[:]
    if xkbmap_mod_meanings:
        for x in DEFAULT_MODIFIER_IGNORE_KEYNAMES:
            mod = xkbmap_mod_meanings.get(x)
            if mod and mod not in mod_ignore:
                mod_ignore.append(mod)
    return mod_ignore


DEFAULT_MODIFIER_NAMES = ["shift", "control", "meta", "super", "hyper", "alt"]

DEFAULT_MODIFIER_IGNORE_KEYNAMES = ["Caps_Lock", "Num_Lock", "Scroll_Lock"]
DEFAULT_MODIFIER_NUISANCE = ["lock", "num", "scroll"]

XMODMAP_MOD_CLEAR = ["clear Lock", "clear Shift", "clear Control",
                 "clear Mod1", "clear Mod2", "clear Mod3", "clear Mod4", "clear Mod5"]
XMODMAP_MOD_ADD = ["add Lock = Caps_Lock",
                 "add Shift = Shift_L Shift_R",
                 "add Control = Control_L Control_R",
                 "add Mod1 = Meta_L Meta_R",
                 "add Mod2 = Alt_L Alt_R",
                 "add Mod3 = Hyper_L Hyper_R",
                 "add Mod4 = Super_L Super_R"]

XMODMAP_MOD_DEFAULTS = ["keycode any = Shift_L",
                   "keycode any = Shift_R",
                   "keycode any = Control_L",
                   "keycode any = Control_R",
                   "keycode any = Meta_L",
                   "keycode any = Meta_R",
                   "keycode any = Alt_L",
                   "keycode any = Alt_R",
                   "keycode any = Hyper_L",
                   "keycode any = Hyper_R",
                   "keycode any = Super_L",
                   "keycode any = Super_R",
                    # Really stupid hack to force backspace to work.
                   "keycode any = BackSpace"]

DEFAULT_MODIFIER_MEANINGS = {
        "Scroll_Lock": "scroll",
        "Num_Lock": "num",
        "Meta_L": "meta",
        "Meta_R": "meta",
        "Super_L": "super",
        "Super_R": "super",
        "Hyper_L": "hyper",
        "Hyper_R": "hyper",
        "Alt_L": "alt",
        "Alt_R": "alt",
        #"ISO_Level3_Shift": "mod5",
        #"Mode_switch": "mod5",
        }

DEFAULT_KEYNAME_FOR_MOD = {
            "shift": "Shift_L",
            "control": "Control_L",
            "meta": "Meta_L",
            "super": "Super_L",
            "hyper": "Hyper_L",
            "alt": "Alt_L",
            }
