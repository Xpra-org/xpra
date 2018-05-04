# This file is part of Xpra.
# Copyright (C) 2010 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2011-2018 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os

from xpra.gtk_common.gtk_util import SHIFT_MASK, LOCK_MASK, META_MASK, CONTROL_MASK, SUPER_MASK, HYPER_MASK
from xpra.platform.keyboard_base import KeyboardBase, log
from xpra.platform.darwin.osx_menu import getOSXMenuHelper


NUM_LOCK_KEYCODE = 71           #HARDCODED!
#a key and the keys we want to translate it into when swapping keys
#(a list so we can hopefully find a good match, best options come first)
KEYS_TRANSLATION_OPTIONS = {
    #try to swap with "Meta" first, fallback to "Alt":
    "Control_L"     : ["Meta_L", "Meta_R", "Alt_L", "Alt_R"],
    "Control_R"     : ["Meta_R", "Meta_L", "Alt_R", "Alt_L"],
    #"Meta" always swapped with "Control"
    "Meta_L"        : ["Control_L", "Control_R"],
    "Meta_R"        : ["Control_R", "Control_L"],
    #"Alt" to "Super" (or "Hyper") so we can distinguish it from "Meta":
    "Alt_L"         : ["Super_L", "Super_R", "Hyper_L", "Hyper_R"],
    "Alt_R"         : ["Super_R", "Super_L", "Hyper_R", "Hyper_L"],
    }
#keys we always want to swap,
#irrespective of the swap-keys option:
ALWAYS_SWAP = os.environ.get("XPRA_MACOS_KEYS_ALWAYS_SWAP", "Alt_L,Alt_R").split(",")


#data extracted from:
#https://support.apple.com/en-us/HT201794
#"How to identify keyboard localizations"
#maps Apple's names into standard X11 keyboard identifiers

APPLE_LAYOUTS = {
    "Arabic"    : "ar",
    "Belgian"   : "be",
    "Bulgarian" : "bg",
    "Croatian"  : "cr",
    "Czech"     : "cz",
    "Danish"    : "dk",
    "Dutch"     : "nl",
    "British"   : "gb",
    "US"        : "us",
    "Finnish"   : "fi",
    "Swedish"   : "se",
    "French"    : "fr",
    "German"    : "de",
    "Greek"     : "gr",
    "Hungarian" : "hu",
    #"Icelandic" : "is",
    "Israel"    : "il",
    "Italian"   : "it",
    "Japanese"  : "jp",
    "Korean"    : "ko",
    "Norwegian" : "no",
    "Portugese" : "po",
    "Romanian"  : "ro",
    "Russian"   : "ru",
    "Slovak"    : "sl",
    "Spanish"   : "es",
    #"Swiss"     : "ch",
    "Taiwanese" : "tw",
    "Thai"      : "th",
    "Turkey"    : "tr",
    }


class Keyboard(KeyboardBase):
    """
        Switch Meta and Control
    """

    def __init__(self):
        KeyboardBase.__init__(self)
        self.init_vars()

    def init_vars(self):
        self.swap_keys = True
        self.meta_modifier = None
        self.control_modifier = "control"
        self.super_modifier = None
        self.hyper_modifier = None
        self.num_lock_modifier = None
        self.num_lock_state = True
        self.num_lock_keycode = NUM_LOCK_KEYCODE
        self.key_translations = {}

    def cleanup(self):
        self.init_vars()
        KeyboardBase.cleanup(self)


    def get_layout_spec(self):
        layout = "us"
        layouts = ["us"]
        variant = ""
        variants = []
        options = ""
        try:
            from AppKit import NSTextInputContext, NSTextView       #@UnresolvedImport
            text_input_context = NSTextInputContext.alloc()
            view = NSTextView.new()
            text_input_context.initWithClient_(view)
            current_keyboard = text_input_context.selectedKeyboardInputSource()
            code = APPLE_LAYOUTS.get(current_keyboard.split(".")[-1])
            log("get_layout_spec() current_keyboard=%s, code=%s", current_keyboard, code)
            all_keyboards = text_input_context.keyboardInputSources()
            log("get_layout_spec() other keyboards=%s", all_keyboards)
            if code:
                layout = code
            if all_keyboards:
                layouts = []
                for k in all_keyboards:
                    code = APPLE_LAYOUTS.get(k.split(".")[-1])
                    if code:
                        layouts.append(code)
                if not layouts:
                    layouts.append("us")
            else:
                if code not in layouts:
                    layouts.insert(0, code)
            log("get_layout_spec() view=%s, input_context=%s, layout=%s, layouts=%s", view, text_input_context, layout, layouts)
        except Exception as e:
            log("get_layout_spec()", exc_info=True)
            log.error("Error querying keyboard layout:")
            log.error(" %s", e)
        return layout, layouts, variant, variants, options

    def get_keymap_modifiers(self):
        """
            Override superclass so we can tell the server
            that 'control' will also be missing from non key events modifiers
        """
        return  {}, [], ["lock", "control"]

    def set_modifier_mappings(self, mappings):
        KeyboardBase.set_modifier_mappings(self, mappings)
        self.meta_modifier = self.modifier_keys.get("Meta_L") or self.modifier_keys.get("Meta_R")
        self.control_modifier = self.modifier_keys.get("Control_L") or self.modifier_keys.get("Control_R") or "control"
        self.super_modifier = self.modifier_keys.get("Super_L") or self.modifier_keys.get("Super_R")
        self.hyper_modifier = self.modifier_keys.get("Hyper_L") or self.modifier_keys.get("Hyper_R")
        self.num_lock_modifier = self.modifier_keys.get("Num_Lock")
        log("set_modifier_mappings(%s) meta=%s, control=%s, super=%s, hyper=%s, numlock=%s", mappings, self.meta_modifier, self.control_modifier, self.super_modifier, self.hyper_modifier, self.num_lock_modifier)
        #find the keysyms and keycodes to use for each key we may translate:
        for orig_keysym, keysyms in KEYS_TRANSLATION_OPTIONS.items():
            new_def = self.find_translation(keysyms)
            if new_def is not None:
                self.key_translations[orig_keysym] = new_def
        log("set_modifier_mappings(..) swap keys translations=%s", self.key_translations)

    def find_translation(self, keysyms):
        log("find_translation(%s)", keysyms)
        new_def = None
        #ie: keysyms : ["Meta_L", "Alt_L"]
        for keysym in keysyms:
            #ie: "Alt_L":
            keycodes_defs = self.modifier_keycodes.get(keysym)
            log("modifier_keycodes(%s)=%s", keysym, keycodes_defs)
            if not keycodes_defs:
                #keysym not found
                continue
            #ie: [(55, 'Alt_L'), (58, 'Alt_L'), 'Alt_L']
            for keycode_def in keycodes_defs:
                if type(keycode_def)==str:      #ie: 'Alt_L'
                    #no keycode found, but better than nothing:
                    new_def = 0, keycode_def    #ie: (0, 'Alt_L')
                    continue
                #an int alone is the keycode:
                if type(keycode_def)==int:
                    if keycode_def>0:
                        #exact match, use it:
                        return keycode_def, keysym
                    new_def = 0, keysym
                    continue
                #below is for compatibility with older servers,
                #(we may be able to remove some of this code already)
                #look for a tuple of (keycode, keysym):
                if type(keycode_def) not in (list, tuple) or len(keycode_def)!=2:
                    continue
                if type(keycode_def[0])!=int or type(keycode_def[1])!=str:
                    continue
                if keycode_def[0]==0:
                    new_def = keycode_def
                    continue
                #found a valid keycode, use this one:
                return keycode_def              #ie: (55, 'Alt_L')
        return new_def


    def mask_to_names(self, mask):
        if self.swap_keys:
            control = self.meta_modifier
            meta = self.control_modifier
        else:
            meta = self.meta_modifier
            control = self.control_modifier
        modmap = {
            SHIFT_MASK      : "shift",
            LOCK_MASK       : "lock",
            SUPER_MASK      : self.super_modifier,
            HYPER_MASK      : self.hyper_modifier,
            META_MASK       : meta,
            CONTROL_MASK    : control,
            }
        names = []
        for modmask, modname in modmap.items():
            if (mask & modmask) and modname:
                names.append(modname)
        #don't trust GTK with numlock:
        if self.num_lock_modifier is not None:
            if self.num_lock_state and self.num_lock_modifier not in names:
                names.append(self.num_lock_modifier)
            elif not self.num_lock_state and self.num_lock_modifier in names:
                names.remove(self.num_lock_modifier)
        log("mask_to_names(%s)=%s swap_keys=%s, modmap=%s, num_lock_state=%s, num_lock_modifier=%s", mask, names, self.swap_keys, modmap, self.num_lock_state, self.num_lock_modifier)
        return names

    def process_key_event(self, send_key_action_cb, wid, key_event):
        if self.swap_keys or key_event.keyname in ALWAYS_SWAP:
            trans = self.key_translations.get(key_event.keyname)
            if trans:
                log("swap keys: translating key '%s' to %s", key_event, trans)
                key_event.keycode, key_event.keyname = trans
        if key_event.keycode==self.num_lock_keycode:
            if not key_event.pressed:
                log("toggling numlock")
                self.num_lock_state = not self.num_lock_state
                getOSXMenuHelper().update_numlock(self.num_lock_state)
            #do not forward the "Escape" key that numlock usually comes up as
            return
        send_key_action_cb(wid, key_event)
