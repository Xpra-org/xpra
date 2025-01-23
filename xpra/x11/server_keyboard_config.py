# -*- coding: utf-8 -*-
# This file is part of Xpra.
# Copyright (C) 2011 Serviware (Arthur Huillet, <ahuillet@serviware.com>)
# Copyright (C) 2010-2023 Antoine Martin <antoine@xpra.org>
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import hashlib
from typing import Dict, Tuple, List, Any

import gi
gi.require_version('Gdk', '3.0')  # @UndefinedVariable
from gi.repository import Gdk  # @UnresolvedImport

from xpra.util import csv, envbool, typedict
from xpra.os_util import bytestostr
from xpra.gtk_common.keymap import get_gtk_keymap
from xpra.gtk_common.gtk_util import get_default_root_window
from xpra.gtk_common.error import xsync, xlog
from xpra.keyboard.mask import DEFAULT_MODIFIER_NUISANCE, DEFAULT_MODIFIER_MEANINGS, DEFAULT_MODIFIER_NUISANCE_KEYNAMES, mask_to_names
from xpra.server.keyboard_config_base import KeyboardConfigBase
from xpra.x11.gtk_x11.keys import grok_modifier_map
from xpra.x11.xkbhelper import (
    do_set_keymap, set_all_keycodes, set_keycode_translation,
    get_modifiers_from_meanings, get_modifiers_from_keycodes,
    clear_modifiers, set_modifiers, map_missing_modifiers,
    clean_keyboard_state, get_keycode_mappings,
    DEBUG_KEYSYMS,
    )
from xpra.x11.bindings.keyboard import X11KeyboardBindings #@UnresolvedImport
from xpra.log import Logger

log = Logger("keyboard")

X11Keyboard = X11KeyboardBindings()

MAP_MISSING_MODIFIERS : bool = envbool("XPRA_MAP_MISSING_MODIFIERS", True)
SHIFT_LOCK : bool = envbool("XPRA_SHIFT_LOCK", False)

ALL_X11_MODIFIERS : Dict[str,int] = {
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
        super().__init__()
        self.raw : bool = False
        self.query_struct = None
        self.modifier_map : Dict[str,int] = {}
        self.mod_meanings = {}
        self.mod_managed = []
        self.mod_pointermissing = []
        self.mod_nuisance = set(DEFAULT_MODIFIER_NUISANCE)
        self.keycodes = ()
        self.x11_keycodes = []
        self.layout = None
        self.variant = None
        self.options = None
        self.layout_groups = False

        #this is shared between clients!
        self.keys_pressed = {}
        #these are derived by calling set_keymap:
        self.keynames_for_mod = {}
        self.keycode_translation = {}
        self.keycodes_for_modifier_keynames = {}
        self.modifier_client_keycodes = {}
        self.compute_modifier_map()
        self.modifiers_filter = []
        self.keycode_mappings = {}

    def __repr__(self):
        return "KeyboardConfig(%s / %s / %s)" % (self.layout, self.variant, self.options)

    def get_info(self) -> Dict[str,Any]:
        info = super().get_info()
        #keycodes:
        if self.keycode_translation:
            ksinfo = info.setdefault("keysym", {})
            kssinf = info.setdefault("keysyms", {})
            kcinfo = info.setdefault("keycode", {})
            for kc, keycode in self.keycode_translation.items():
                if isinstance(kc, tuple):
                    a, b = kc
                    if isinstance(a, int):
                        client_keycode, keysym = a, b
                        ksinfo.setdefault(keysym, {})[client_keycode] = keycode
                        kcinfo.setdefault(client_keycode, {})[keysym] = keycode
                    elif isinstance(b, int):
                        keysym, index = a, b
                        kssinf.setdefault(keycode, []).append((index, keysym))
                else:
                    kcinfo[kc] = keycode
        if self.keycodes:
            i = 0
            kminfo = info.setdefault("keymap", {})
            for keyval, name, keycode, group, level in self.keycodes:
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
        if self.mod_meanings:
            for mod, mod_name in self.mod_meanings.items():
                modinfo[mod] = mod_name
        info["x11_keycode"] = self.x11_keycodes
        for x in ("layout", "variant", "options", "mod_managed", "mod_pointermissing", "raw", "layout_groups"):
            v = getattr(self, x)
            if v:
                info[x] = v
        modsinfo["nuisance"] = tuple(self.mod_nuisance or [])
        info["modifier"] = modinfo
        info["modifiers"] = modsinfo
        info["keys-pressed"] = self.keys_pressed
        #this would need to always run in the UI thread:
        #info["state"] = {
        #    "modifiers" : self.get_current_mask(),
        #    }
        log("keyboard info: %s", info)
        return info


    def parse_options(self, props) -> int:
        """ used by both process_hello and process_keymap
            to set the keyboard attributes """
        super().parse_options(props)
        modded = {}
        #clients version 4.4 and later use a 'keymap' substructure:
        keymap_dict = typedict(props.dictget("keymap") or {})
        def parse_option(name, parse_fn, old_parse_fn, *parse_args):
            cv = getattr(self, name)
            if keymap_dict:
                nv = parse_fn(name, *parse_args)
            else:
                nv = old_parse_fn("xkbmap_%s" % name, *parse_args)
            if cv!=nv:
                setattr(self, name, nv)
                modded[name] = nv
        #lists:
        parse_option("keycodes", keymap_dict.tupleget, props.tupleget)
        #dicts:
        for x in ("mod_meanings", "x11_keycodes", "query_struct"):
            parse_option(x, keymap_dict.dictget, props.dictget, {})
        #lists of strings:
        for x in ("mod_managed", "mod_pointermissing"):
            parse_option(x, keymap_dict.strtupleget, props.strtupleget)
        parse_option("raw", keymap_dict.boolget, props.boolget)
        #older clients don't specify if they support layout groups safely
        #(MS Windows clients used base-1)
        #so only enable it by default for X11 clients
        parse_option("layout_groups", keymap_dict.boolget, props.boolget, bool(self.query_struct))
        log("assign_keymap_options(..) modified %s", modded)
        return len(modded)>0

    def parse_layout(self, props) -> None:
        """ used by both process_hello and process_keymap """
        #clients version 4.4 and later use a 'keymap' substructure:
        keymap_dict = typedict(props.dictget("keymap") or {})
        def l(k):
            return keymap_dict.strget(k, props.get(f"xkbmap_{k}"))
        self.layout = l("layout")
        self.variant = l("variant")
        self.options = l("options")


    def get_hash(self) -> str:
        """
            This hash will be different whenever the keyboard configuration changes.
        """
        m = hashlib.sha256()
        def hashadd(v):
            m.update(("/%s" % str(v)).encode("utf8"))
        m.update(super().get_hash())
        for x in (self.raw, self.mod_meanings, self.mod_pointermissing, self.keycodes, self.x11_keycodes):
            hashadd(x)
        if self.query_struct:
            #flatten the dict in a predicatable order:
            for k in sorted(self.query_struct.keys()):
                hashadd(self.query_struct.get(k))
        return "%s/%s/%s/%s" % (self.layout, self.variant, self.options, m.hexdigest())

    def compute_modifiers(self) -> None:
        if self.raw:
            with xsync:
                mod_mappings = X11Keyboard.get_modifier_mappings()
            self.mod_meanings = {}
            self.keycodes_for_modifier_keynames = {}
            for mod, mod_defs in mod_mappings.items():
                for mod_def in mod_defs:
                    for v in mod_def:
                        if isinstance(v, int):
                            l = self.keycodes_for_modifier_keynames.setdefault(mod, [])
                        else:
                            self.mod_meanings[v] = mod
                            l = self.keynames_for_mod.setdefault(mod, [])
                        if v not in l:
                            l.append(v)
        else:
            log("compute_modifiers() mod_meanings=%s", self.mod_meanings)
            log("compute_modifiers() keycodes=%s", self.keycodes)
            if self.mod_meanings:
                #Unix-like OS provides modifier meanings:
                self.keynames_for_mod = get_modifiers_from_meanings(self.mod_meanings)
            elif self.keycodes:
                #non-Unix-like OS provides just keycodes for now:
                self.keynames_for_mod = get_modifiers_from_keycodes(self.keycodes, MAP_MISSING_MODIFIERS)
                if MAP_MISSING_MODIFIERS:
                    map_missing_modifiers(self.keynames_for_mod)
            else:
                log.info("client did not supply any modifier definitions, using defaults")
                self.keynames_for_mod = get_modifiers_from_meanings(DEFAULT_MODIFIER_MEANINGS)
                if MAP_MISSING_MODIFIERS:
                    map_missing_modifiers(self.keynames_for_mod)
        log("compute_modifiers() keynames_for_mod=%s", self.keynames_for_mod)
        log("compute_modifiers() keycodes_for_modifier_keynames=%s", self.keycodes_for_modifier_keynames)
        log("compute_modifiers() mod_meanings=%s", self.mod_meanings)


    def compute_modifier_keynames(self) -> None:
        self.keycodes_for_modifier_keynames = {}
        self.mod_nuisance = set(DEFAULT_MODIFIER_NUISANCE)
        display = Gdk.Display.get_default()
        keymap = Gdk.Keymap.get_for_display(display)
        if self.keynames_for_mod:
            for modifier, keynames in self.keynames_for_mod.items():
                for keyname in keynames:
                    if keyname in DEFAULT_MODIFIER_NUISANCE_KEYNAMES:
                        self.mod_nuisance.add(modifier)
                    keyval = Gdk.keyval_from_name(bytestostr(keyname))
                    if keyval==0:
                        log.error("Error: no keyval found for keyname '%s' (modifier '%s')", keyname, modifier)
                        continue
                    entries = keymap.get_entries_for_keyval(keyval)
                    if entries:
                        keycodes = []
                        if entries[0] is True:
                            keycodes = [entry.keycode for entry in entries[1]]
                        for keycode in keycodes:
                            l = self.keycodes_for_modifier_keynames.setdefault(keyname, [])
                            if keycode not in l:
                                l.append(keycode)
        log("compute_modifier_keynames: keycodes_for_modifier_keynames=%s", self.keycodes_for_modifier_keynames)

    def compute_client_modifier_keycodes(self) -> None:
        """ The keycodes for all modifiers (those are *client* keycodes!) """
        try:
            server_mappings = X11Keyboard.get_modifier_mappings()
            log("compute_client_modifier_keycodes() server mappings=%s", server_mappings)
            #update the mappings to use the keycodes the client knows about:
            reverse_trans = {}
            for k,v in self.keycode_translation.items():
                reverse_trans[v] = k
            self.modifier_client_keycodes = {}
            self.mod_nuisance = set(DEFAULT_MODIFIER_NUISANCE)
            for modifier, keys in server_mappings.items():
                #ie: modifier=mod3, keys=[(115, 'Super_L'), (116, 'Super_R'), (127, 'Super_L')]
                client_keydefs = []
                for keycode,keysym in keys:
                    #ie: keycode=115, keysym=Super_L
                    client_def = reverse_trans.get(keycode, (0, keysym))
                    #ie: client_def = (99, Super_L)
                    #ie: client_def = Super_L
                    #ie: client_def = (0, Super_L)
                    if isinstance(client_def, (list, tuple)):
                        #ie:
                        # keycode, keysym:
                        #  client_def = (99, Super_L)
                        # or keysym, level:
                        #  client_def = (Super_L, 1)
                        client_keydefs.append(client_def)
                    elif client_def==keysym:
                        #ie: client_def = Super_L
                        client_keydefs.append((keycode, keysym))
                    #record nuisacnde modifiers:
                    if keysym in DEFAULT_MODIFIER_NUISANCE_KEYNAMES:
                        self.mod_nuisance.add(modifier)
                self.modifier_client_keycodes[modifier] = client_keydefs
            log("compute_client_modifier_keycodes() mappings=%s", self.modifier_client_keycodes)
            log("compute_client_modifier_keycodes() mod nuisance=%s", self.mod_nuisance)
        except Exception as e:
            log.error("Error: compute_client_modifier_keycodes: %s" % e, exc_info=True)

    def compute_modifier_map(self) -> None:
        with xlog:
            self.modifier_map = grok_modifier_map(Gdk.Display.get_default(), self.mod_meanings)
        log("modifier_map(%s)=%s", self.mod_meanings, self.modifier_map)


    def is_modifier(self, keycode:int) -> bool:
        for mod, keys in self.keycodes_for_modifier_keynames.items():
            if keycode in keys:
                log("is_modifier(%s) found modifier: %s", keycode, mod)
                return True
        log("is_modifier(%s) not found", keycode)
        return False


    def set_layout(self, layout:str, variant:str, options) -> bool:
        log("set_layout(%s, %s, %s)", layout, variant, options)
        if layout=="en":
            log.warn("Warning: invalid keyboard layout name '%s', using 'us' instead", layout)
            layout = "us"
        if layout!=self.layout or variant!=self.variant or options!=self.options:
            self.layout = layout
            self.variant = variant
            self.options = options
            return True
        return False


    def set_keymap(self, translate_only:bool=False) -> None:
        if not self.enabled:
            return
        log("set_keymap(%s) layout=%r, variant=%r, options=%r, query-struct=%r",
            translate_only, self.layout, self.variant, self.options, self.query_struct)
        if translate_only:
            self.keycode_translation = set_keycode_translation(self.x11_keycodes, self.keycodes)
            self.add_gtk_keynames()
            self.add_loose_matches()
            self.compute_modifiers()
            self.compute_modifier_keynames()
            self.compute_client_modifier_keycodes()
            self.update_keycode_mappings()
            return

        with xlog:
            clean_keyboard_state()
            do_set_keymap(self.layout, self.variant, self.options, self.query_struct)
        log("set_keymap: query_struct=%r", self.query_struct)
        with xlog:
            #first clear all existing modifiers:
            clean_keyboard_state()

            if not self.raw:
                clear_modifiers()
                clean_keyboard_state()

                #now set all the keycodes:
                #first compute the modifier maps as this may have an influence
                #on the keycode mappings (at least for the from_keycodes case):
                self.compute_modifiers()
                #key translation:
                if self.x11_keycodes and self.query_struct:
                    #native full mapping of all keycodes:
                    self.keycode_translation = set_all_keycodes(self.x11_keycodes, self.keycodes, False, self.keynames_for_mod)
                elif self.keycodes:
                    #if the client does not provide a full native keymap with all the keycodes,
                    #try to preserve the initial server keycodes and translate the client keycodes instead:
                    #(used by non X11 clients like osx,win32 or HTML5)
                    self.keycode_translation = set_keycode_translation(self.x11_keycodes, self.keycodes)
                else:
                    self.keycode_translation = {}
                self.add_gtk_keynames()

                #now set the new modifier mappings:
                clean_keyboard_state()
                log("going to set modifiers, mod_meanings=%s, len(keycodes)=%s, keynames_for_mod=%s", self.mod_meanings, len(self.keycodes or []), self.keynames_for_mod)
                if self.keynames_for_mod:
                    set_modifiers(self.keynames_for_mod)
                log("keynames_for_mod=%s", self.keynames_for_mod)
                self.compute_modifier_keynames()
            else:
                self.keycode_translation = {}
                log("keyboard raw mode, keycode translation left empty")
                self.compute_modifiers()
            self.compute_client_modifier_keycodes()
            log("keyname_for_mod=%s", self.keynames_for_mod)
            clean_keyboard_state()
            self.update_keycode_mappings()
            self.add_loose_matches()


    def add_gtk_keynames(self) -> None:
        #add the keynames we find via gtk
        #since we may rely on finding those keynames from the client
        #(used with non-native keymaps)
        log("add_gtk_keynames() gtk keymap=%s", get_gtk_keymap())
        for _, keyname, keycode, _, _ in get_gtk_keymap():
            if keyname not in self.keycode_translation:
                self.keycode_translation[keyname] = keycode
                if keyname in DEBUG_KEYSYMS:
                    log.info("add_gtk_keynames: %s=%s", keyname, keycode)

    def add_loose_matches(self) -> None:
        # add lowercase versions of all keynames
        for key, keycode in tuple(self.keycode_translation.items()):
            if isinstance(key, str) and not key.islower():
                self.keycode_translation[key.lower()] = keycode

    def set_default_keymap(self) -> None:
        """
        assign a default keymap based on the current X11 server keymap
        sets up the translation tables,
        so we can look up keys without setting a client keymap.
        """
        if not self.enabled:
            return
        with xsync:
            clean_keyboard_state()
            #keycodes:
            keycode_to_keynames = get_keycode_mappings()
            self.keycode_translation = {}
            #prefer keycodes that don't use the lowest level+mode:
            default_for_keyname : Dict[str,Tuple[int,int]] = {}
            for keycode, keynames in keycode_to_keynames.items():
                for i, keyname in enumerate(keynames):
                    self.keycode_translation[(keyname, i)] = keycode
                    if keyname in DEBUG_KEYSYMS:
                        log.info("set_default_keymap: %s=%s", (keyname, i), keycode)
                    kd = default_for_keyname.get(keyname)
                    if kd is None or kd[1]>i:
                        default_for_keyname[keyname] = (keycode, i)
            for keyname, kd in default_for_keyname.items():
                keycode = kd[0]
                self.keycode_translation[keyname] = keycode
                if keyname in DEBUG_KEYSYMS:
                    log.info("set_default_keymap: %s=%s", keyname, keycode)
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
            self.update_keycode_mappings()

    def update_keycode_mappings(self) -> None:
        self.keycode_mappings = get_keycode_mappings()


    def kmlog(self, keyname, msg, *args) -> None:
        """ logs at info level is we are debugging this keyname """
        if keyname in DEBUG_KEYSYMS:
            l = log.info
        else:
            l = log
        l(msg, *args)

    def do_get_keycode(self, client_keycode:int, keyname:str, pressed:bool, modifiers, keyval, keystr:str, group:int):
        if not self.enabled:
            self.kmlog(keyname, "ignoring keycode since keyboard is turned off")
            return -1, group
        if keyname=="0xffffff":
            return -1, group
        if self.raw:
            return client_keycode, group
        if self.x11_keycodes:
            keycode = self.keycode_translation.get((client_keycode, keyname)) or client_keycode
            self.kmlog(keyname, "do_get_keycode (%i, %s)=%s (native keymap)", client_keycode, keyname, keycode)
            return keycode, group
        return self.find_matching_keycode(client_keycode, keyname, pressed, modifiers, keyval, keystr, group)

    def find_matching_keycode(self, client_keycode:int, keyname:str,
                              pressed:bool, modifiers, keyval, keystr:str, group) -> Tuple[int,int]:
        """
        from man xmodmap:
        The list of keysyms is assigned to the indicated keycode (which may be specified in decimal,
        hex or octal and can be determined by running the xev program).
        Up to eight keysyms may be attached to a key, however the last four are not used in any major
        X server implementation.
        The first keysym is used when no modifier key is pressed in conjunction with this key,
        the second with Shift, the third when the Mode_switch key is used with this key and
        the fourth when both the Mode_switch and Shift keys are used.
        """
        keycode = None
        rgroup = group
        def klog(msg, *args):
            self.kmlog(keyname, "do_get_keycode%s"+msg, (client_keycode, keyname, pressed, modifiers, keyval, keystr, group), *args)
        def kmlog(msg, *args):
            self.kmlog(keyname, msg, *args)
        #non-native: try harder to find matching keysym
        #first, try to honour shift state:
        lock = ("lock" in modifiers) and (SHIFT_LOCK or (bool(keystr) and keystr.isalpha()))
        shift = ("shift" in modifiers) ^ lock
        mode = 0
        numlock = 0
        numlock_modifier = None
        for mod, keynames in self.keynames_for_mod.items():
            if "Num_Lock" in keynames:
                numlock_modifier = mod
                break
        for mod in modifiers:
            names = self.keynames_for_mod.get(mod, [])
            if "Num_Lock" in names:
                numlock = 1
            for name in names:
                if name in ("ISO_Level3_Shift", "Mode_switch"):
                    mode = 1
                    break
        levels = []
        #try to preserve the mode (harder to toggle):
        for m in (int(bool(mode)), int(not mode)):
            #try to preserve shift state:
            for s in (int(bool(shift)), int(not shift)):
                #group is comparatively easier to toggle (one function call):
                for g in (int(bool(group)), int(not group)):
                    level = int(g)*4 + int(m)*2 + int(s)*1
                    levels.append(level)
        kmlog("will try levels: %s", levels)
        for level in levels:
            keycode = self.keycode_translation.get((keyname, level))
            if keycode:
                keysyms = self.keycode_mappings.get(keycode)
                klog("=%i (level=%i, shift=%s, mode=%i, keysyms=%s)", keycode, level, shift, mode, keysyms)
                level0 = levels[0]
                uq_keysyms = set(keysyms)
                if len(uq_keysyms)<=1 or (len(keysyms)>level0 and keysyms[level0]==""):
                    #if the keysym we would match for this keycode is 'NoSymbol',
                    #then we can probably ignore it ('NoSymbol' shows up as "")
                    #same if there's only one actual keysym for this keycode
                    kmlog("not toggling any modifiers state for keysyms=%s", keysyms)
                    break
                def toggle_modifier(mod):
                    keynames = self.keynames_for_mod.get(mod, ())
                    if keyname in keynames:
                        kmlog("not toggling '%s' since '%s' should deal with it", mod, keyname)
                        #the keycode we're returning is for this modifier,
                        #assume that this will end up doing what is needed
                        return
                    if mod in modifiers:
                        kmlog("removing '%s' from modifiers", mod)
                        modifiers.remove(mod)
                    else:
                        kmlog("adding '%s' to modifiers", mod)
                        modifiers.append(mod)
                #keypad overrules shift state (see #2702):
                if keyname.startswith("KP_"):
                    if numlock_modifier and not numlock:
                        toggle_modifier(numlock_modifier)
                elif (level & 1) ^ shift:
                    #shift state does not match
                    toggle_modifier("shift")
                if int(bool(level & 2)) ^ mode:
                    #try to set / unset mode:
                    for mod, keynames in self.keynames_for_mod.items():
                        if "ISO_Level3_Shift" in keynames or "Mode_switch" in keynames:
                            #found mode switch modified
                            toggle_modifier(mod)
                            break
                rgroup = level//4
                if rgroup!=group:
                    kmlog("switching group from %i to %i", group, rgroup)
                break
        #this should not find anything new?:
        if keycode is None:
            keycode = self.keycode_translation.get(keyname, -1)
            klog("=%i, %i (keyname translation)", keycode, rgroup)
        if keycode is None:
            #last resort, find using the keyval:
            display = Gdk.Display.get_default()
            keymap = Gdk.Keymap.get_for_display(display)
            b, entries = keymap.get_entries_for_keyval(keyval)
            if b and entries:
                for entry in entries:
                    if entry.group==group:
                        return entry.keycode, entry.group
        return keycode or 0, rgroup or 0

    def get_current_mask(self) -> List:
        root = get_default_root_window()
        if not root:
            return []
        current_mask = X11Keyboard.query_mask()
        return mask_to_names(current_mask, self.modifier_map)

    def make_keymask_match(self, modifier_list, ignored_modifier_keycode=None, ignored_modifier_keynames=None) -> None:
        """
            Given a list of modifiers that should be set, try to press the right keys
            to make the server's modifier list match it.
            Things to take into consideration:
            * mod_managed is a list of modifiers which are "server-managed":
                these never show up in the client's modifier list as it is not aware of them,
                so we just always leave them as they are and rely on some client key event to toggle them.
                ie: "num" on win32, which is toggled by the "Num_Lock" key presses.
            * when called from '_handle_key', we ignore the modifier key which may be pressed
                or released as it should be set by that key press event.
            * when called from mouse position/click/focus events we ignore 'mod_pointermissing'
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
                return modifier in (self.mod_pointermissing or [])
        else:
            #keyboard event: ignore the keynames specified
            #(usually the modifier key being pressed/unpressed)
            def is_ignored(_modifier, modifier_keynames):
                return len(set(modifier_keynames or []) & set(ignored_modifier_keynames or []))>0

        def filtered_modifiers_set(modifiers):
            m = set()
            mm = self.mod_managed or ()
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
                keynames = self.keynames_for_mod.get(modifier, None)
                if keynames is None:
                    log.error("Error: unknown modifier '%s'", modifier)
                    log.error(" known modifiers: %s", csv(self.keynames_for_mod.keys()))
                    continue
                if not keynames:
                    log.warn("Warning: found no keynames for '%s'", modifier)
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
                nuisance = modifier in self.mod_nuisance
                log("keynames(%s)=%s, keycodes=%s, nuisance=%s, nuisance keys=%s", modifier, keynames, keycodes, nuisance, self.mod_nuisance)
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
                        log(" trying to unpress it!")
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

        with xsync:
            current = filtered_modifiers_set(self.get_current_mask())
            wanted = filtered_modifiers_set(modifier_list or [])
            if current==wanted:
                return
            log("make_keymask_match(%s) current mask: %s, wanted: %s, ignoring=%s/%s, keys_pressed=%s", modifier_list, current, wanted, ignored_modifier_keycode, ignored_modifier_keynames, self.keys_pressed)
            fr = change_mask(current.difference(wanted), False, "remove")
            fa = change_mask(wanted.difference(current), True, "add")
            if not fr or fa:
                return
            if fr:
                log.warn("Warning: failed to remove the following modifiers:")
                log.warn(" %s", csv(fr))
            if fa:
                log.warn("Warning: failed to add the following modifiers:")
                log.warn(" %s", csv(fa))
            #this should never happen.. but if it does?
            #something didn't work, use the big hammer and start again from scratch:
            log.warn(" keys still pressed=%s", X11Keyboard.get_keycodes_down())
            X11Keyboard.unpress_all_keys()
            log.warn(" doing a full keyboard reset, keys now pressed=%s", X11Keyboard.get_keycodes_down())
            #and try to set the modifiers one last time:
            current = filtered_modifiers_set(self.get_current_mask())
            change_mask(current.difference(wanted), False, "remove")
            change_mask(wanted.difference(current), True, "add")
