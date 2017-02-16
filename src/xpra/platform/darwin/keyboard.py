# This file is part of Xpra.
# Copyright (C) 2010 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2011-2017 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.


from xpra.gtk_common.gtk_util import META_MASK
from xpra.platform.keyboard_base import KeyboardBase, log
from xpra.platform.darwin.osx_menu import getOSXMenuHelper


NUM_LOCK_KEYCODE = 71           #HARDCODED!
#a key and the keys we want to translate it into when swapping keys
#(a list so we can hopefully find a good match)
KEYS_TRANSLATION_OPTIONS = {
                    "Control_L"     : ["Alt_L", "Meta_L"],
                    "Control_R"     : ["Alt_R", "Meta_R"],
                    "Meta_L"        : ["Control_L", "Control_R"],
                    "Meta_R"        : ["Control_R", "Control_L"],
                    }

class Keyboard(KeyboardBase):
    """
        Switch Meta and Control
    """

    def __init__(self):
        self.swap_keys = True
        self.meta_modifier = None
        self.control_modifier = None
        self.num_lock_modifier = None
        self.num_lock_state = True
        self.num_lock_keycode = NUM_LOCK_KEYCODE
        self.key_translations = {}


    def get_layout_spec(self):
        layout = "us"
        layouts = ["us"]
        variant = ""
        variants = []
        try:
            from xpra.platform.darwin.keyboard_layout import get_keyboard_layout
            i = get_keyboard_layout()
            log("get_keyboard_layout()=%s", i)
            locale = i["locale"]        #ie: "en_GB"
            parts = locale.split("_")
            if len(parts)==2:
                layout = parts[1].lower()
                layouts = [layout, 'us']
        except Exception as e:
            log("get_layout_spec()", exc_info=True)
            log.error("Error querying keyboard layout:")
            log.error(" %s", e)
        return layout, layouts, variant, variants

    def get_keymap_modifiers(self):
        """
            Override superclass so we can tell the server
            that 'control' will also be missing from non key events modifiers
        """
        return  {}, [], ["lock", "control"]

    def set_modifier_mappings(self, mappings):
        KeyboardBase.set_modifier_mappings(self, mappings)
        self.meta_modifier = self.modifier_keys.get("Meta_L") or self.modifier_keys.get("Meta_R")
        self.control_modifier = self.modifier_keys.get("Control_L") or self.modifier_keys.get("Control_R")
        self.num_lock_modifier = self.modifier_keys.get("Num_Lock")
        log("set_modifier_mappings(%s) meta=%s, control=%s, numlock=%s", mappings, self.meta_modifier, self.control_modifier, self.num_lock_modifier)
        #find the keysyms and keycodes to use for each key we may translate:
        for orig_keysym in KEYS_TRANSLATION_OPTIONS.keys():
            new_def = self.find_translation(orig_keysym)
            if new_def is not None:
                self.key_translations[orig_keysym] = new_def
        log("set_modifier_mappings(..) swap keys translations=%s", self.key_translations)

    def find_translation(self, orig_keysym):
        new_def = None
        #ie: keysyms : ["Meta_L", "Alt_L"]
        keysyms = KEYS_TRANSLATION_OPTIONS.get(orig_keysym)
        for keysym in keysyms:
            #ie: "Alt_L":
            keycodes_defs = self.modifier_keycodes.get(keysym)
            if not keycodes_defs:
                #keysym not found
                continue
            #ie: [(55, 'Alt_L'), (58, 'Alt_L'), 'Alt_L']
            for keycode_def in keycodes_defs:
                if type(keycode_def)==str:      #ie: 'Alt_L'
                    #no keycode found, but better than nothing:
                    new_def = 0, keycode_def    #ie: (0, 'Alt_L')
                    continue
                #look for a tuple of (keycode, keysym):
                if type(keycode_def) not in (list, tuple):
                    continue
                if type(keycode_def[0])!=int or type(keycode_def[1])!=str:
                    continue
                #found one, use that:
                return keycode_def           #(55, 'Alt_L')
        return new_def


    def mask_to_names(self, mask):
        names = KeyboardBase.mask_to_names(self, mask)
        if self.swap_keys and self.meta_modifier is not None and self.control_modifier is not None:
            meta_on = bool(mask & META_MASK)
            meta_set = self.meta_modifier in names
            control_set = self.control_modifier in names
            log("mask_to_names names=%s, meta_on=%s, meta_set=%s, control_set=%s", names, meta_on, meta_set, control_set)
            if meta_on and not control_set:
                log("mask_to_names swapping meta for control: %s for %s", self.meta_modifier, self.control_modifier)
                names.append(self.control_modifier)
                if meta_set:
                    names.remove(self.meta_modifier)
            elif control_set and not meta_on:
                log("mask_to_names swapping control for meta: %s for %s", self.control_modifier, self.meta_modifier)
                names.remove(self.control_modifier)
                if not meta_set:
                    names.append(self.meta_modifier)
        #deal with numlock:
        if self.num_lock_modifier is not None:
            if self.num_lock_state and self.num_lock_modifier not in names:
                names.append(self.num_lock_modifier)
            elif not self.num_lock_state and self.num_lock_modifier in names:
                names.remove(self.num_lock_modifier)
        log("mask_to_names(%s)=%s", mask, names)
        return names

    def process_key_event(self, send_key_action_cb, wid, key_event):
        if self.swap_keys:
            trans = self.key_translations.get(key_event.keyname)
            if trans:
                log("swap keys: translating key '%s' to %s", key_event, trans)
                key_event.keycode, key_event.keyname = trans
        if key_event.keycode==self.num_lock_keycode and not key_event.pressed:
            log("toggling numlock")
            self.num_lock_state = not self.num_lock_state
            getOSXMenuHelper().update_numlock(self.num_lock_state)
        send_key_action_cb(wid, key_event)
