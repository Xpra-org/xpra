# This file is part of Xpra.
# Copyright (C) 2010 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2011-2013 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.


from xpra.platform.keyboard_base import KeyboardBase, debug
from xpra.platform.darwin.osx_menu import getOSXMenuHelper


NUM_LOCK_KEYCODE = 71           #HARDCODED!


class Keyboard(KeyboardBase):
    """
        Switch Meta_L and Control_L
    """

    def __init__(self):
        self.swap_keys = True
        self.meta_modifier = None
        self.control_modifier = None
        self.num_lock_modifier = None
        self.num_lock_state = True
        self.num_lock_keycode = NUM_LOCK_KEYCODE
        getOSXMenuHelper().keyboard = self

    def set_modifier_mappings(self, mappings):
        KeyboardBase.set_modifier_mappings(self, mappings)
        self.meta_modifier = self.modifier_keys.get("Meta_L")
        self.control_modifier = self.modifier_keys.get("Control_L")
        self.num_lock_modifier = self.modifier_keys.get("Num_Lock")
        debug("set_modifier_mappings(%s) meta=%s, control=%s, numlock=%s", mappings, self.meta_modifier, self.control_modifier, self.num_lock_modifier)

    def mask_to_names(self, mask):
        names = KeyboardBase.mask_to_names(self, mask)
        debug("mask_to_names(%s) meta_modifier=%s, control_modifier=%s", mask, self.meta_modifier, self.control_modifier)
        if self.swap_keys and self.meta_modifier is not None and self.control_modifier is not None:
            #we have the modifier names for both keys we may need to switch
            if self.meta_modifier in names and self.control_modifier not in names:
                names.remove(self.meta_modifier)
                names.append(self.control_modifier)
            elif self.control_modifier in names and self.meta_modifier not in names:
                names.remove(self.control_modifier)
                names.append(self.meta_modifier)
        if self.num_lock_modifier is not None:
            if self.num_lock_state and self.num_lock_modifier not in names:
                names.append(self.num_lock_modifier)
            elif not self.num_lock_state and self.num_lock_modifier in names:
                names.remove(self.num_lock_modifier)
        debug("mask_to_names(%s)=%s", mask, names)
        return names

    def process_key_event(self, send_key_action_cb, wid, key_event):
        if self.meta_modifier is not None and self.control_modifier is not None:
            #we have the modifier names for both keys we may need to switch
            if key_event.keyname=="Control_L":
                debug("process_key_event swapping Control_L for Meta_L")
                key_event.keyname = "Meta_L"
            elif key_event.keyname=="Meta_L":
                debug("process_key_event swapping Meta_L for Control_L")
                key_event.keyname = "Control_L"
        if key_event.keycode==self.num_lock_keycode and not key_event.pressed:
            debug("toggling numlock")
            self.num_lock_state = not self.num_lock_state
            getOSXMenuHelper().update_numlock(self.num_lock_state)
        send_key_action_cb(wid, key_event)
