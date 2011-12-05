# This file is part of Parti.
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Parti is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

MODIFIER_NAMES = ["shift", "control", "meta", "super", "hyper", "alt"]

def mask_to_names(mask, modifier_map):
    modifiers = []
    for modifier in MODIFIER_NAMES:
        modifier_mask = modifier_map[modifier]
        if modifier_mask & mask:
            modifiers.append(modifier)
            mask &= ~modifier_mask
    return modifiers

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
