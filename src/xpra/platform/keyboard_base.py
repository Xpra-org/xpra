# This file is part of Xpra.
# Copyright (C) 2010 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2011-2014 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.keyboard.mask import mask_to_names, MODIFIER_MAP
from xpra.log import Logger
from xpra.os_util import bytestostr
log = Logger("keyboard")


class KeyboardBase(object):

    def __init__(self):
        self.modifier_mappings = {}
        self.modifier_keys = {}
        self.modifier_keycodes = {}
        #FIXME: this only allows a single modifier per mask
        #and in some cases we want to allow other modifier names
        #to use the same mask... (ie: META on OSX)
        self.modifier_map = MODIFIER_MAP

    def cleanup(self):
        pass

    def has_bell(self):
        return False

    def set_modifier_mappings(self, mappings):
        log("set_modifier_mappings(%s)", mappings)
        self.modifier_mappings = mappings
        self.modifier_keys = {}
        self.modifier_keycodes = {}
        for modifier, keys in mappings.items():
            for keycode,keyname in keys:
                self.modifier_keys[bytestostr(keyname)] = bytestostr(modifier)
                keycodes = self.modifier_keycodes.setdefault(bytestostr(keyname), [])
                if keycode not in keycodes:
                    keycodes.append(keycode)
        log("modifier_keys=%s", self.modifier_keys)
        log("modifier_keycodes=%s", self.modifier_keycodes)

    def mask_to_names(self, mask):
        return mask_to_names(mask, self.modifier_map)

    def get_keymap_modifiers(self):
        """
            ask the server to manage capslock ('lock') which can be missing from mouse events
            (or maybe this is virtualbox causing it?)
        """
        return  {}, [], ["lock"]

    def get_keymap_spec(self):
        return "", "", {}

    def get_x11_keymap(self):
        return {}

    def get_layout_spec(self):
        return "", [], "", None, ""

    def get_keyboard_repeat(self):
        return None

    def update_modifier_map(self, _display, _xkbmap_mod_meanings):
        self.modifier_map = MODIFIER_MAP


    def process_key_event(self, send_key_action_cb, wid, key_event):
        #default is to just send it as-is:
        send_key_action_cb(wid, key_event)
