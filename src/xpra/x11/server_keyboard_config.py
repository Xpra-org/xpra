# -*- coding: utf-8 -*-
# This file is part of Xpra.
# Copyright (C) 2011 Serviware (Arthur Huillet, <ahuillet@serviware.com>)
# Copyright (C) 2010-2017 Antoine Martin <antoine@devloop.org.uk>
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.


from xpra.log import Logger
log = Logger("keyboard")


from xpra.util import csv, nonl, envbool
from xpra.os_util import bytestostr
from xpra.gtk_common.keymap import get_gtk_keymap
from xpra.x11.gtk_x11.keys import grok_modifier_map
from xpra.gtk_common.gtk_util import get_default_keymap, display_get_default, get_default_root_window
from xpra.keyboard.mask import DEFAULT_MODIFIER_NUISANCE, DEFAULT_MODIFIER_NUISANCE_KEYNAMES, mask_to_names
from xpra.server.keyboard_config_base import KeyboardConfigBase
from xpra.x11.xkbhelper import do_set_keymap, set_all_keycodes, set_keycode_translation, \
                           get_modifiers_from_meanings, get_modifiers_from_keycodes, \
                           clear_modifiers, set_modifiers, map_missing_modifiers, \
                           clean_keyboard_state
from xpra.gtk_common.error import xsync
from xpra.gtk_common.gobject_compat import import_gdk, is_gtk3
from xpra.x11.bindings.keyboard_bindings import X11KeyboardBindings #@UnresolvedImport
X11Keyboard = X11KeyboardBindings()

MAP_MISSING_MODIFIERS = envbool("XPRA_MAP_MISSING_MODIFIERS", True)

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


class KeyboardConfig(KeyboardConfigBase):
    def __init__(self):
        KeyboardConfigBase.__init__(self)
        self.xkbmap_raw = False
        self.xkbmap_print = None
        self.xkbmap_query = None
        self.xkbmap_query_struct = None
        self.xkbmap_mod_meanings = {}
        self.xkbmap_mod_managed = []
        self.xkbmap_mod_pointermissing = []
        self.xkbmap_mod_nuisance = set(DEFAULT_MODIFIER_NUISANCE)
        self.xkbmap_keycodes = []
        self.xkbmap_x11_keycodes = []
        self.xkbmap_layout = None
        self.xkbmap_variant = None
        self.xkbmap_options = None
        self.xkbmap_layout_groups = False

        #this is shared between clients!
        self.keys_pressed = {}
        #these are derived by calling set_keymap:
        self.keynames_for_mod = {}
        self.keycode_translation = {}
        self.keycodes_for_modifier_keynames = {}
        self.modifier_client_keycodes = {}
        self.compute_modifier_map()
        self.modifiers_filter = []

    def __repr__(self):
        return "KeyboardConfig(%s / %s / %s)" % (self.xkbmap_layout, self.xkbmap_variant, self.xkbmap_options)

    def get_info(self):
        info = KeyboardConfigBase.get_info(self)
        #keycodes:
        if self.keycode_translation:
            ksinfo = info.setdefault("keysym", {})
            kcinfo = info.setdefault("keycode", {})
            for kc, keycode in self.keycode_translation.items():
                if type(kc)==tuple:
                    client_keycode, keysym = kc
                    ksinfo.setdefault(keysym, {})[client_keycode] = keycode
                    kcinfo.setdefault(client_keycode, {})[keysym] = keycode
                else:
                    kcinfo[kc] = keycode
        if self.xkbmap_keycodes:
            i = 0
            kminfo = info.setdefault("keymap", {})
            for keyval, name, keycode, group, level in self.xkbmap_keycodes:
                kminfo[i] = (keyval, name, keycode, group, level)
                i += 1
        #modifiers:
        modinfo = {}
        modsinfo = {}
        modinfo["filter"] = self.modifiers_filter
        if self.modifier_client_keycodes:
            for mod, keys in self.modifier_client_keycodes.items():
                modinfo.setdefault(mod, {})["client_keys"] = keys
        if self.keynames_for_mod:
            for mod, keys in self.keynames_for_mod.items():
                modinfo.setdefault(mod, {})["keys"] = tuple(keys)
        if self.keycodes_for_modifier_keynames:
            for mod, keys in self.keycodes_for_modifier_keynames.items():
                modinfo.setdefault(mod, {})["keycodes"] = tuple(keys)
        if self.xkbmap_mod_meanings:
            for mod, mod_name in self.xkbmap_mod_meanings.items():
                modinfo[mod] = mod_name
        info["x11_keycode"] = self.xkbmap_x11_keycodes
        for x in ("print", "layout", "variant", "mod_managed", "mod_pointermissing", "raw", "layout_groups"):
            v = getattr(self, "xkbmap_"+x.replace("-", "_"))
            if v:
                info[x] = v
        modsinfo["nuisance"] = tuple(self.xkbmap_mod_nuisance or [])
        info["modifier"] = modinfo
        info["modifiers"] = modsinfo
        log("keyboard info: %s", info)
        return info


    def parse_options(self, props):
        """ used by both process_hello and process_keymap
            to set the keyboard attributes """
        KeyboardConfigBase.parse_options(self, props)
        modded = {}
        def parse_option(name, parse_fn, *parse_args):
            prop = "xkbmap_%s" % name
            cv = getattr(self, prop)
            nv = parse_fn(prop, *parse_args)
            if cv!=nv:
                setattr(self, prop, nv)
                modded[prop] = nv
        #plain strings:
        for x in ("print", "query"):
            parse_option(x, props.strget)
        #lists:
        parse_option("keycodes", props.listget)
        #dicts:
        for x in ("mod_meanings", "x11_keycodes", "query_struct"):
            parse_option(x, props.dictget)
        #lists of strings:
        for x in ("mod_managed", "mod_pointermissing"):
            parse_option(x, props.strlistget)
        parse_option("raw", props.boolget)
        #older clients don't specify if they support layout groups safely
        #(MS Windows clients used base-1)
        #so only enable it by default for X11 clients
        parse_option("layout_groups", props.boolget, bool(self.xkbmap_query or self.xkbmap_query_struct))
        log("assign_keymap_options(..) modified %s", modded)
        return len(modded)>0


    def get_hash(self):
        """
            This hash will be different whenever the keyboard configuration changes.
        """
        import hashlib
        m = hashlib.sha1()
        def hashadd(v):
            m.update(("/%s" % str(v)).encode("utf8"))
        m.update(KeyboardConfigBase.get_hash(self))
        for x in (self.xkbmap_print, self.xkbmap_query, self.xkbmap_raw, \
                  self.xkbmap_mod_meanings, self.xkbmap_mod_pointermissing, \
                  self.xkbmap_keycodes, self.xkbmap_x11_keycodes):
            hashadd(x)
        if self.xkbmap_query_struct:
            #flatten the dict in a predicatable order:
            for k in sorted(self.xkbmap_query_struct.keys()):
                hashadd(self.xkbmap_query_struct.get(k))
        return "%s/%s/%s/%s" % (self.xkbmap_layout, self.xkbmap_variant, self.xkbmap_options, m.hexdigest())

    def compute_modifier_keynames(self):
        self.keycodes_for_modifier_keynames = {}
        self.xkbmap_mod_nuisance = set(DEFAULT_MODIFIER_NUISANCE)
        keymap = get_default_keymap()
        gdk = import_gdk()
        if self.keynames_for_mod:
            for modifier, keynames in self.keynames_for_mod.items():
                for keyname in keynames:
                    if keyname in DEFAULT_MODIFIER_NUISANCE_KEYNAMES:
                        self.xkbmap_mod_nuisance.add(modifier)
                    keyval = gdk.keyval_from_name(keyname)
                    if keyval==0:
                        log.error("Error: no keyval found for keyname '%s' (modifier '%s')", keyname, modifier)
                        return  []
                    entries = keymap.get_entries_for_keyval(keyval)
                    if entries:
                        keycodes = []
                        if is_gtk3():
                            if entries[0] is True:
                                keycodes = [entry.keycode for entry in entries[1]]
                        else:
                            keycodes = [entry[0] for entry in entries]
                        for keycode in keycodes:
                            l = self.keycodes_for_modifier_keynames.setdefault(keyname, [])
                            if keycode not in l:
                                l.append(keycode)
        log("compute_modifier_keynames: keycodes_for_modifier_keynames=%s", self.keycodes_for_modifier_keynames)

    def compute_client_modifier_keycodes(self):
        """ The keycodes for all modifiers (those are *client* keycodes!) """
        try:
            server_mappings = X11Keyboard.get_modifier_mappings()
            log("compute_client_modifier_keycodes() server mappings=%s", server_mappings)
            #update the mappings to use the keycodes the client knows about:
            reverse_trans = {}
            for k,v in self.keycode_translation.items():
                reverse_trans[v] = k
            self.modifier_client_keycodes = {}
            self.xkbmap_mod_nuisance = set(DEFAULT_MODIFIER_NUISANCE)
            for modifier, keys in server_mappings.items():
                #ie: modifier=mod3, keys=[(115, 'Super_L'), (116, 'Super_R'), (127, 'Super_L')]
                client_keydefs = []
                for keycode,keysym in keys:
                    #ie: keycode=115, keysym=Super_L
                    client_def = reverse_trans.get(keycode, (0, keysym))
                    #ie: client_def = (99, Super_L)
                    #ie: client_def = Super_L
                    #ie: client_def = (0, Super_L)
                    if type(client_def) in (list, tuple):
                        #ie: client_def = (99, Super_L)
                        client_keydefs.append(client_def)
                    elif client_def==keysym:
                        #ie: client_def = Super_L
                        client_keydefs.append((keycode, keysym))
                    #record nuisacnde modifiers:
                    if keysym in DEFAULT_MODIFIER_NUISANCE_KEYNAMES:
                        self.xkbmap_mod_nuisance.add(modifier)
                self.modifier_client_keycodes[modifier] = client_keydefs
            log("compute_client_modifier_keycodes() mappings=%s", self.modifier_client_keycodes)
            log("compute_client_modifier_keycodes() mod nuisance=%s", self.xkbmap_mod_nuisance)
        except Exception as e:
            log.error("Error: compute_client_modifier_keycodes: %s" % e, exc_info=True)

    def compute_modifier_map(self):
        self.modifier_map = grok_modifier_map(display_get_default(), self.xkbmap_mod_meanings)
        log("modifier_map(%s)=%s", self.xkbmap_mod_meanings, self.modifier_map)


    def is_modifier(self, keycode):
        for mod, keys in self.keycodes_for_modifier_keynames.items():
            if keycode in keys:
                log("is_modifier(%s) found modifier: %s", keycode, mod)
                return True
        log("is_modifier(%s) not found", keycode)
        return False


    def set_layout(self, layout, variant, options):
        log("set_layout(%s, %s, %s)", layout, variant, options)
        if layout!=self.xkbmap_layout or variant!=self.xkbmap_variant or options!=self.xkbmap_options:
            self.xkbmap_layout = layout
            self.xkbmap_variant = variant
            self.xkbmap_options = options
            return True
        return False


    def set_keymap(self, translate_only=False):
        if not self.enabled:
            return
        log("set_keymap(%s) layout=%s, variant=%s, options=%s, print=%s, query=%s", translate_only, self.xkbmap_layout, self.xkbmap_variant, self.xkbmap_options, nonl(self.xkbmap_print), nonl(self.xkbmap_query))
        if translate_only:
            self.keycode_translation = set_keycode_translation(self.xkbmap_x11_keycodes, self.xkbmap_keycodes)
            self.add_gtk_keynames()
            self.compute_modifier_keynames()
            self.compute_client_modifier_keycodes()
            return

        try:
            with xsync:
                clean_keyboard_state()
                do_set_keymap(self.xkbmap_layout, self.xkbmap_variant, self.xkbmap_options,
                              self.xkbmap_print, self.xkbmap_query, self.xkbmap_query_struct)
        except:
            log.error("Error setting up new keymap", exc_info=True)
        log("set_keymap: xkbmap_print=%s, xkbmap_query=%s", nonl(self.xkbmap_print), nonl(self.xkbmap_query))
        try:
            with xsync:
                #first clear all existing modifiers:
                clean_keyboard_state()

                if not self.xkbmap_raw:
                    clear_modifiers(ALL_X11_MODIFIERS.keys())       #just clear all of them (set or not)

                    #now set all the keycodes:
                    clean_keyboard_state()

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
                        self.keynames_for_mod = get_modifiers_from_keycodes(self.xkbmap_keycodes, MAP_MISSING_MODIFIERS)
                        if MAP_MISSING_MODIFIERS:
                            map_missing_modifiers(self.keynames_for_mod)
                    else:
                        log.warn("Warning: client did not supply any modifier definitions")
                        self.keynames_for_mod = {}
                    if bool(self.xkbmap_query):
                        #native full mapping of all keycodes:
                        self.keycode_translation = set_all_keycodes(self.xkbmap_x11_keycodes, self.xkbmap_keycodes, False, self.keynames_for_mod)
                    else:
                        #if the client does not provide a full native keymap with all the keycodes,
                        #try to preserve the initial server keycodes and translate the client keycodes instead:
                        #(used by non X11 clients like osx,win32 or HTML5)
                        self.keycode_translation = set_keycode_translation(self.xkbmap_x11_keycodes, self.xkbmap_keycodes)
                    self.add_gtk_keynames()

                    #now set the new modifier mappings:
                    clean_keyboard_state()
                    log("going to set modifiers, xkbmap_mod_meanings=%s, len(xkbmap_keycodes)=%s, keynames_for_mod=%s", self.xkbmap_mod_meanings, len(self.xkbmap_keycodes or []), self.keynames_for_mod)
                    if self.keynames_for_mod:
                        set_modifiers(self.keynames_for_mod)
                    log("keynames_for_mod=%s", self.keynames_for_mod)
                    self.compute_modifier_keynames()
                else:
                    self.keycode_translation = {}
                    log("keyboard raw mode, keycode translation left empty")
                    log("keycode mappings=%s", X11Keyboard.get_keycode_mappings())
                    mod_mappings = X11Keyboard.get_modifier_mappings()
                    self.xkbmap_mod_meanings = {}
                    for mod, mod_defs in mod_mappings.items():
                        for mod_def in mod_defs:
                            for v in mod_def:
                                if type(v)==int:
                                    l = self.keycodes_for_modifier_keynames.setdefault(mod, [])
                                else:
                                    self.xkbmap_mod_meanings[v] = mod
                                    l = self.keynames_for_mod.setdefault(mod, [])
                                if v not in l:
                                    l.append(v)
                    log("keynames_for_mod=%s", self.keynames_for_mod)
                    log("keycodes_for_modifier_keynames=%s", self.keycodes_for_modifier_keynames)
                    log("mod_meanings=%s", self.xkbmap_mod_meanings)
                self.compute_client_modifier_keycodes()
                log("keyname_for_mod=%s", self.keynames_for_mod)
                clean_keyboard_state()
        except:
            log.error("Error setting X11 keyboard modifier map", exc_info=True)

    def add_gtk_keynames(self):
        #add the keynames we find via gtk
        #since we may rely on finding those keynames from the client
        #(used with non native keymaps)
        for _, keyname, keycode, _, _ in get_gtk_keymap():
            if keyname not in self.keycode_translation:
                self.keycode_translation[keyname] = keycode

    def set_default_keymap(self):
        """ assign a default keymap based on the current X11 server keymap
            sets up the translation tables so we can lookup keys without
            setting a client keymap.
        """
        if not self.enabled:
            return
        clean_keyboard_state()
        #keycodes:
        keycode_to_keynames = X11Keyboard.get_keycode_mappings()
        self.keycode_translation = {}
        for keycode, keynames in keycode_to_keynames.items():
            for keyname in keynames:
                self.keycode_translation[keyname] = keycode
        self.add_gtk_keynames()
        log("set_default_keymap: keycode_translation=%s", self.keycode_translation)
        #modifiers:
        self.keynames_for_mod = {}
        #ie: {'control': [(37, 'Control_L'), (105, 'Control_R')], ...}
        mod_mappings = X11Keyboard.get_modifier_mappings()
        log("set_default_keymap: using modifier mappings=%s", mod_mappings)
        for modifier, mappings in mod_mappings.items():
            keynames = []
            for m in mappings:      #ie: (37, 'Control_L'), (105, 'Control_R')
                if len(m)==2:
                    keynames.append(m[1])   #ie: 'Control_L'
            self.keynames_for_mod[modifier] = set(keynames)
        self.compute_modifier_keynames()
        self.compute_client_modifier_keycodes()
        log("set_default_keymap: keynames_for_mod=%s", self.keynames_for_mod)
        log("set_default_keymap: keycodes_for_modifier_keynames=%s", self.keycodes_for_modifier_keynames)
        log("set_default_keymap: modifier_map=%s", self.modifier_map)


    def get_keycode(self, client_keycode, keyname, modifiers):
        if not self.enabled:
            log("ignoring keycode since keyboard is turned off")
            return -1
        keycode = self.keycode_translation.get((client_keycode, keyname))
        if keycode is None:
            #non-native: try harder to find matching keysym
            keycode = self.keycode_translation.get(keyname, client_keycode)
            log("get_keycode(%s, %s, %s) keyname lookup: %s", client_keycode, keyname, modifiers, keycode)
        else:
            log("get_keycode(%s, %s, %s) keyname+keycode lookup: %s", client_keycode, keyname, modifiers, keycode)
        return keycode


    def get_current_mask(self):
        current_mask = get_default_root_window().get_pointer()[-1]
        return mask_to_names(current_mask, self.modifier_map)

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
            * when called from mouse position/click/focus events we ignore 'xkbmap_mod_pointermissing'
                which is set by the client to indicate modifiers which are missing from mouse events.
                ie: on win32, "lock" is missing.
                (we know this is not a keyboard event because ignored_modifier_keynames is None..)
            * if the modifier is a "nuisance" one ("lock", "num", "scroll") then we must
                simulate a full keypress (down then up).
            * some modifiers can be set by multiple keys ("shift" by both "Shift_L" and "Shift_R" for example)
                so we try to find the matching modifier in the currently pressed keys (keys_pressed)
                to make sure we unpress the right one.
        """
        if not self.keynames_for_mod:
            log("make_keymask_match: ignored as keynames_for_mod not assigned yet")
            return
        if ignored_modifier_keynames is None:
            #this is not a keyboard event, ignore modifiers in "mod_pointermissing"
            def is_ignored(modifier, _modifier_keynames):
                return modifier in (self.xkbmap_mod_pointermissing or [])
        else:
            #keyboard event: ignore the keynames specified
            #(usually the modifier key being pressed/unpressed)
            def is_ignored(_modifier, modifier_keynames):
                return len(set(modifier_keynames or []) & set(ignored_modifier_keynames or []))>0

        def filtered_modifiers_set(modifiers):
            m = set()
            mm = self.xkbmap_mod_managed or ()
            for modifier in modifiers:
                modifier = bytestostr(modifier)
                if modifier in mm:
                    log("modifier is server managed: %s", modifier)
                    continue
                keynames = self.keynames_for_mod.get(modifier)
                if is_ignored(modifier, keynames):
                    log("modifier '%s' ignored (in ignored keynames=%s)", modifier, keynames)
                    continue
                m.add(modifier)
            log("filtered_modifiers_set(%s)=%s", modifiers, m)
            return m

        def change_mask(modifiers, press, info):
            failed = []
            for modifier in modifiers:
                modifier = bytestostr(modifier)
                keynames = self.keynames_for_mod.get(modifier)
                if not keynames:
                    log.error("Error: unknown modifier '%s'", modifier)
                    continue
                #find the keycodes that match the keynames for this modifier
                keycodes = []
                #log.info("keynames(%s)=%s", modifier, keynames)
                for keyname in keynames:
                    if keyname in self.keys_pressed.values():
                        #found the key which was pressed to set this modifier
                        for keycode, name in self.keys_pressed.items():
                            if name==keyname:
                                log("found the key pressed for %s: %s", modifier, name)
                                keycodes.insert(0, keycode)
                    keycodes_for_keyname = self.keycodes_for_modifier_keynames.get(keyname)
                    if keycodes_for_keyname:
                        for keycode in keycodes_for_keyname:
                            if keycode not in keycodes:
                                keycodes.append(keycode)
                if ignored_modifier_keycode is not None and ignored_modifier_keycode in keycodes:
                    log("modifier '%s' ignored (ignored keycode=%s)", modifier, ignored_modifier_keycode)
                    continue
                #nuisance keys (lock, num, scroll) are toggled by a
                #full key press + key release (so act accordingly in the loop below)
                nuisance = modifier in self.xkbmap_mod_nuisance
                log("keynames(%s)=%s, keycodes=%s, nuisance=%s, nuisance keys=%s", modifier, keynames, keycodes, nuisance, self.xkbmap_mod_nuisance)
                modkeycode = None
                if not press:
                    #since we want to unpress something,
                    #let's try the keycodes we know are pressed first:
                    kdown = X11Keyboard.get_keycodes_down()
                    pressed = [x for x in keycodes if x in kdown]
                    others = [x for x in keycodes if x not in kdown]
                    keycodes = pressed+others
                for keycode in keycodes:
                    if nuisance:
                        X11Keyboard.xtest_fake_key(keycode, True)
                        X11Keyboard.xtest_fake_key(keycode, False)
                    else:
                        X11Keyboard.xtest_fake_key(keycode, press)
                    new_mask = self.get_current_mask()
                    success = (modifier in new_mask)==press
                    if success:
                        modkeycode = keycode
                        log("change_mask(%s) %s modifier '%s' using keycode %s", info, modifier_list, modifier, keycode)
                        break   #we're done for this modifier
                    log("%s %s with keycode %s did not work", info, modifier, keycode)
                    if press and not nuisance:
                        log(" trying to unpress it!", info, modifier, keycode)
                        X11Keyboard.xtest_fake_key(keycode, False)
                        #maybe doing the full keypress (down+up) worked:
                        new_mask = self.get_current_mask()
                        if (modifier in new_mask)==press:
                            break
                    log("change_mask(%s) %s modifier '%s' using keycode %s, success: %s", info, modifier_list, modifier, keycode, success)
                if not modkeycode:
                    failed.append(modifier)
            log("change_mask(%s, %s, %s) failed=%s", modifiers, press, info, failed)
            return failed

        current = filtered_modifiers_set(self.get_current_mask())
        wanted = filtered_modifiers_set(modifier_list or [])
        if current==wanted:
            return
        log("make_keymask_match(%s) current mask: %s, wanted: %s, ignoring=%s/%s, keys_pressed=%s", modifier_list, current, wanted, ignored_modifier_keycode, ignored_modifier_keynames, self.keys_pressed)
        fr = change_mask(current.difference(wanted), False, "remove")
        fa = change_mask(wanted.difference(current), True, "add")
        if fr:
            log.warn("Warning: failed to remove the following modifiers:")
            log.warn(" %s", csv(fr))
        elif fa:
            log.warn("Warning: failed to add the following modifiers:")
            log.warn(" %s", csv(fa))
        else:
            return  #all good!
        #this should never happen.. but if it does?
        #something didn't work, use the big hammer and start again from scratch:
        log.warn(" keys still pressed=%s", X11Keyboard.get_keycodes_down())
        X11Keyboard.unpress_all_keys()
        log.warn(" doing a full keyboard reset, keys now pressed=%s", X11Keyboard.get_keycodes_down())
        #and try to set the modifiers one last time:
        current = filtered_modifiers_set(self.get_current_mask())
        change_mask(current.difference(wanted), False, "remove")
        change_mask(wanted.difference(current), True, "add")
