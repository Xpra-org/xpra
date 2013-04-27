# coding=utf8
# This file is part of Xpra.
# Copyright (C) 2011 Serviware (Arthur Huillet, <ahuillet@serviware.com>)
# Copyright (C) 2010-2013 Antoine Martin <antoine@devloop.org.uk>
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import gtk.gdk

from xpra.log import Logger
log = Logger()

from xpra.x11.gtk_x11.keys import grok_modifier_map
from xpra.keyboard.mask import DEFAULT_MODIFIER_NUISANCE, mask_to_names
from xpra.x11.xkbhelper import do_set_keymap, set_all_keycodes, \
                           get_modifiers_from_meanings, get_modifiers_from_keycodes, \
                           clear_modifiers, set_modifiers, \
                           clean_keyboard_state
from xpra.x11.lowlevel import xtest_fake_key, get_modifier_mappings     #@UnresolvedImport

import os
XPRA_KEYBOARD_DEBUG = os.environ.get("XPRA_KEYBOARD_DEBUG", "0")!="0"
if XPRA_KEYBOARD_DEBUG:
    debug = log.info
else:
    debug = log.debug

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


class KeyboardConfig(object):
    def __init__(self):
        self.xkbmap_print = None
        self.xkbmap_query = None
        self.xkbmap_mod_meanings = {}
        self.xkbmap_mod_managed = []
        self.xkbmap_mod_pointermissing = []
        self.xkbmap_keycodes = []
        self.xkbmap_x11_keycodes = []
        self.xkbmap_layout = None
        self.xkbmap_variant = None

        self.enabled = True
        #this is shared between clients!
        self.keys_pressed = {}
        #these are derived by calling set_keymap:
        self.keynames_for_mod = None
        self.keycode_translation = {}
        self.keycodes_for_modifier_keynames = {}
        self.modifier_client_keycodes = {}
        self.compute_modifier_map()
        self.modifiers_filter = None
        self.is_native_keymap = True

    def get_hash(self):
        try:
            import hashlib
            m = hashlib.sha1()
        except:
            #try python2.4 variant:
            import sha
            m = sha.new()
        for x in (self.xkbmap_print, self.xkbmap_query, \
                  self.xkbmap_mod_meanings, self.xkbmap_mod_pointermissing, \
                  self.xkbmap_keycodes, self.xkbmap_x11_keycodes):
            m.update("/%s" % str(x))
        return "%s/%s/%s" % (self.xkbmap_layout, self.xkbmap_variant, m.hexdigest())

    def compute_modifier_keynames(self):
        self.keycodes_for_modifier_keynames = {}
        keymap = gtk.gdk.keymap_get_default()
        if self.keynames_for_mod:
            for modifier, keynames in self.keynames_for_mod.items():
                for keyname in keynames:
                    keyval = gtk.gdk.keyval_from_name(keyname)
                    if keyval==0:
                        log.error("no keyval found for keyname %s (modifier %s)", keyname, modifier)
                        return  []
                    entries = keymap.get_entries_for_keyval(keyval)
                    if entries:
                        for keycode, _, _ in entries:
                            self.keycodes_for_modifier_keynames.setdefault(keyname, set()).add(keycode)
        debug("compute_modifier_keynames: keycodes_for_modifier_keynames=%s", self.keycodes_for_modifier_keynames)

    def compute_client_modifier_keycodes(self):
        """ The keycodes for all modifiers (those are *client* keycodes!) """
        try:
            server_mappings = get_modifier_mappings()
            debug("get_modifier_mappings=%s", server_mappings)
            #update the mappings to use the keycodes the client knows about:
            reverse_trans = {}
            for k,v in self.keycode_translation.items():
                reverse_trans[v] = k
            self.modifier_client_keycodes = {}
            for modifier, keys in server_mappings.items():
                client_keycodes = []
                for keycode,keyname in keys:
                    client_keycode = reverse_trans.get(keycode, keycode)
                    if client_keycode:
                        client_keycodes.append((client_keycode, keyname))
                self.modifier_client_keycodes[modifier] = client_keycodes
            debug("compute_client_modifier_keycodes() mappings=%s", self.modifier_client_keycodes)
        except Exception, e:
            log.error("do_set_keymap: %s" % e, exc_info=True)

    def compute_modifier_map(self):
        self.modifier_map = grok_modifier_map(gtk.gdk.display_get_default(), self.xkbmap_mod_meanings)
        debug("modifier_map(%s)=%s", self.xkbmap_mod_meanings, self.modifier_map)


    def set_keymap(self, client_platform):
        if not self.enabled:
            return
        clean_keyboard_state()
        try:
            do_set_keymap(self.xkbmap_layout, self.xkbmap_variant,
                          self.xkbmap_print, self.xkbmap_query)
        except:
            log.error("error setting new keymap", exc_info=True)
        self.is_native_keymap = self.xkbmap_print!="" or self.xkbmap_query!=""
        try:
            #first clear all existing modifiers:
            clean_keyboard_state()
            clear_modifiers(ALL_X11_MODIFIERS.keys())       #just clear all of them (set or not)

            #now set all the keycodes:
            clean_keyboard_state()
            self.keycode_translation = {}

            has_keycodes = (self.xkbmap_x11_keycodes and len(self.xkbmap_x11_keycodes)>0) or \
                            (self.xkbmap_keycodes and len(self.xkbmap_keycodes)>0)
            assert has_keycodes, "client failed to provide any keycodes!"
            #first compute the modifier maps as this may have an influence
            #on the keycode mappings (at least for the from_keycodes case):
            if self.xkbmap_mod_meanings:
                #Unix-like OS provides modifier meanings:
                self.keynames_for_mod = get_modifiers_from_meanings(self.xkbmap_mod_meanings)
            elif self.xkbmap_keycodes:
                #non-Unix-like OS provides just keycodes for now:
                self.keynames_for_mod = get_modifiers_from_keycodes(self.xkbmap_keycodes)
            else:
                log.error("missing both xkbmap_mod_meanings and xkbmap_keycodes, modifiers will probably not work as expected!")
                self.keynames_for_mod = {}
            #if the client does not provide a full keymap,
            #try to preserve the initial server keycodes
            #(used by non X11 clients like osx,win32 or Android)
            preserve_server_keycodes = not self.xkbmap_print and not self.xkbmap_query
            self.keycode_translation = set_all_keycodes(self.xkbmap_x11_keycodes, self.xkbmap_keycodes, preserve_server_keycodes, self.keynames_for_mod)

            #now set the new modifier mappings:
            clean_keyboard_state()
            debug("going to set modifiers, xkbmap_mod_meanings=%s, len(xkbmap_keycodes)=%s", self.xkbmap_mod_meanings, len(self.xkbmap_keycodes or []))
            if self.keynames_for_mod:
                set_modifiers(self.keynames_for_mod)
            self.compute_modifier_keynames()
            self.compute_client_modifier_keycodes()
            debug("keyname_for_mod=%s", self.keynames_for_mod)
        except:
            log.error("error setting xmodmap", exc_info=True)
        if (client_platform and client_platform.startswith("win")) and not self.is_native_keymap:
            self.modifiers_filter = ["lock"]
            num_mods = [mod for mod,keynames in self.keynames_for_mod.items() if "Num_Lock" in keynames]
            if len(num_mods)==1:
                self.modifiers_filter.append(num_mods[0])
            else:
                log.warn("found more than one modifier for 'Num_Lock': %s", num_mods)

    def make_keymask_match(self, modifier_list, ignored_modifier_keycode=None, ignored_modifier_keynames=None):
        """
            Given a list of modifiers that should be set, try to press the right keys
            to make the server's modifier list match it.
            Things to take into consideration:
            * xkbmap_mod_managed is a list of modifiers which are "server-managed":
                these never show up in the client's modifier list as it is not aware of them,
                so we just always leave them as they are and rely on some client key event to toggle them.
                ie: "num" on win32, which is toggled by the "Num_Lock" key presses.
            * when called from '_handle_key', we ignore the modifier key which may be pressed
                or released as it should be set by that key press event.
            * when called from mouse position/click events we ignore 'xkbmap_mod_pointermissing'
                which is set by the client to indicate modifiers which are missing from mouse events.
                ie: on win32, "lock" is missing.
            * if the modifier is a "nuisance" one ("lock", "num", "scroll") then we must
                simulate a full keypress (down then up).
            * some modifiers can be set by multiple keys ("shift" by both "Shift_L" and "Shift_R" for example)
                so we try to find the matching modifier in the currently pressed keys (keys_pressed)
                to make sure we unpress the right one.
        """
        def get_current_mask():
            _, _, current_mask = gtk.gdk.get_default_root_window().get_pointer()
            return mask_to_names(current_mask, self.modifier_map)

        if not self.keynames_for_mod:
            debug("make_keymask_match: ignored as keynames_for_mod not assigned yet")
            return
        if ignored_modifier_keynames is None:
            ignored_modifier_keynames = self.xkbmap_mod_pointermissing

        def is_ignored(modifier_keynames):
            if not ignored_modifier_keynames:
                return False
            for imk in ignored_modifier_keynames:
                if imk in modifier_keynames:
                    debug("modifier ignored (ignored keyname=%s)", imk)
                    return True
            return False

        def filter_modifiers(mods):
            if self.modifiers_filter is None:
                return mods
            return [x for x in mods if x in self.modifiers_filter]

        current = set(filter_modifiers(get_current_mask()))
        wanted = set(filter_modifiers(modifier_list))
        if current==wanted:
            return
        debug("make_keymask_match(%s) current mask: %s, wanted: %s, ignoring=%s/%s, keys_pressed=%s", modifier_list, current, wanted, ignored_modifier_keycode, ignored_modifier_keynames, self.keys_pressed)
        display = gtk.gdk.display_get_default()

        def change_mask(modifiers, press, info):
            for modifier in modifiers:
                if self.xkbmap_mod_managed and modifier in self.xkbmap_mod_managed:
                    debug("modifier is server managed: %s", modifier)
                    continue
                keynames = self.keynames_for_mod.get(modifier)
                if not keynames:
                    log.error("unknown modifier: %s", modifier)
                    continue
                if is_ignored(keynames):
                    debug("modifier %s ignored (in ignored keynames=%s)", modifier, keynames)
                    continue
                #find the keycodes that match the keynames for this modifier
                keycodes = []
                #log.info("keynames(%s)=%s", modifier, keynames)
                for keyname in keynames:
                    if keyname in self.keys_pressed.values():
                        #found the key which was pressed to set this modifier
                        for keycode, name in self.keys_pressed.items():
                            if name==keyname:
                                debug("found the key pressed for %s: %s", modifier, name)
                                keycodes.insert(0, keycode)
                    keycodes_for_keyname = self.keycodes_for_modifier_keynames.get(keyname)
                    if keycodes_for_keyname:
                        for keycode in keycodes_for_keyname:
                            if keycode not in keycodes:
                                keycodes.append(keycode)
                if ignored_modifier_keycode is not None and ignored_modifier_keycode in keycodes:
                    debug("modifier %s ignored (ignored keycode=%s)", modifier, ignored_modifier_keycode)
                    continue
                #nuisance keys (lock, num, scroll) are toggled by a
                #full key press + key release (so act accordingly in the loop below)
                nuisance = modifier in DEFAULT_MODIFIER_NUISANCE
                debug("keynames(%s)=%s, keycodes=%s, nuisance=%s", modifier, keynames, keycodes, nuisance)
                for keycode in keycodes:
                    if nuisance:
                        xtest_fake_key(display, keycode, True)
                        xtest_fake_key(display, keycode, False)
                    else:
                        xtest_fake_key(display, keycode, press)
                    new_mask = get_current_mask()
                    success = (modifier in new_mask)==press
                    debug("make_keymask_match(%s) %s modifier %s using %s, success: %s", info, modifier_list, modifier, keycode, success)
                    if success:
                        break
                    elif not nuisance:
                        debug("%s %s with keycode %s did not work - trying to undo it!", info, modifier, keycode)
                        xtest_fake_key(display, keycode, not press)
                        new_mask = get_current_mask()
                        #maybe doing the full keypress (down+up or u+down) worked:
                        if (modifier in new_mask)==press:
                            break

        change_mask(current.difference(wanted), False, "remove")
        change_mask(wanted.difference(current), True, "add")
