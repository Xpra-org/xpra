#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2011-2013 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.


MODIFIER_MAP = {
            "shift":    1 << 0,
            "lock":     1 << 1,
            "control":  1 << 2,
            "mod1":     1 << 3,
            "mod2":     1 << 4,
            "mod3":     1 << 5,
            "mod4":     1 << 6,
            "mod5":     1 << 7,
            }


DEFAULT_MODIFIER_NAMES = ["shift", "control"]
DEFAULT_MODIFIER_NUISANCE_KEYNAMES = ["Num_Lock", "Caps_Lock", "Scroll_Lock"]
DEFAULT_MODIFIER_NUISANCE = ["lock"]
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

def mask_to_names(mask, modifier_map):
    modifiers = []
    for modifier, modifier_mask in modifier_map.items():
        if modifier_mask & mask:
            modifiers.append(modifier)
            mask &= ~modifier_mask
    return modifiers
