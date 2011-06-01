# This file is part of Parti.
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Parti is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.platform.gui import grok_modifier_map

def mask_to_names(mask, modifier_map):
    modifiers = []
    for modifier in ["shift", "control",
                     "meta", "super", "hyper", "alt",
                     ]:
        modifier_mask = modifier_map[modifier]
        if modifier_mask & mask:
            modifiers.append(modifier)
            mask &= ~modifier_mask
    return modifiers
