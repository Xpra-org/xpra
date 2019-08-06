# This file is part of Xpra.
# Copyright (C) 2011 Serviware (Arthur Huillet, <ahuillet@serviware.com>)
# Copyright (C) 2010-2017 Antoine Martin <antoine@xpra.org>
# Copyright (C) 2008, 2010 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os

from xpra.util import nonl, csv, std, envbool, print_nested_dict, repr_ellipsized
from xpra.os_util import POSIX, bytestostr
from xpra.log import Logger

log = Logger("keyboard")

LAYOUT_GROUPS = envbool("XPRA_LAYOUT_GROUPS", True)


class KeyboardHelper(object):

    def __init__(self, net_send, keyboard_sync=True,
                 shortcut_modifiers="auto", key_shortcuts=(),
                 raw=False, layout="", layouts=(),
                 variant="", variants=(), options=""):
        self.reset_state()
        self.send = net_send
        self.locked = False
        self.keyboard_sync = keyboard_sync
        self.shortcut_modifiers = shortcut_modifiers
        self.key_shortcuts = self.parse_shortcuts(key_shortcuts)
        #command line overrides:
        self.xkbmap_raw = raw
        self.layout_option = layout
        self.variant_option = variant
        self.layouts_option = layouts
        self.variants_option = variants
        self.options = options
        #the platform class which allows us to map the keys:
        from xpra.platform.keyboard import Keyboard
        self.keyboard = Keyboard()      #pylint: disable=not-callable
        log("KeyboardHelper(%s) keyboard=%s",
            (net_send, keyboard_sync, key_shortcuts,
             raw, layout, layouts, variant, variants, options), self.keyboard)
        key_repeat = self.keyboard.get_keyboard_repeat()
        if key_repeat:
            self.key_repeat_delay, self.key_repeat_interval = key_repeat

    def mask_to_names(self, mask):
        return self.keyboard.mask_to_names(mask)

    def set_modifier_mappings(self, mappings):
        self.keyboard.set_modifier_mappings(mappings)

    def reset_state(self):
        self.xkbmap_keycodes = []
        self.xkbmap_x11_keycodes = {}
        self.xkbmap_mod_meanings = {}
        self.xkbmap_mod_managed = []
        self.xkbmap_mod_pointermissing = []
        self.xkbmap_layout = ""
        self.xkbmap_layouts = []
        self.xkbmap_variant = ""
        self.xkbmap_variants = []
        self.xkbmap_options = ""
        self.xkbmap_print = ""
        self.xkbmap_query = ""
        self.xkbmap_query_struct = {}
        self.xkbmap_layout_groups = LAYOUT_GROUPS
        self.xkbmap_raw = False

        self.hash = None

        self.key_repeat_delay = -1
        self.key_repeat_interval = -1
        self.keyboard_sync = False
        self.key_shortcuts = {}

    def cleanup(self):
        self.reset_state()
        def nosend(*_args):
            pass
        self.send = nosend

    def keymap_changed(self, *args):
        pass


    def parse_shortcuts(self, strs):
        if not strs:
            """ if none are defined, add this as default
            it would be nicer to specify it via OptionParser in main
            but then it would always have to be there with no way of removing it
            whereas now it is enough to define one (any shortcut)
            """
            strs = ["meta+shift+F4:quit"]
        log("parse_shortcuts(%s)" % str(strs))
        shortcuts = {}
        #modifier names contains the internal modifiers list, ie: "mod1", "control", ...
        #but the user expects the name of the key to be used, ie: "alt" or "super"
        #whereas at best, we keep "Alt_L" : "mod1" mappings... (xposix)
        #so generate a map from one to the other:
        modifier_names = {}
        from xpra.keyboard.mask import DEFAULT_MODIFIER_MEANINGS, DEFAULT_MODIFIER_NUISANCE
        meanings = self.xkbmap_mod_meanings or DEFAULT_MODIFIER_MEANINGS
        DEFAULT_MODIFIER_IGNORE_KEYNAMES = ["Caps_Lock", "Num_Lock", "Scroll_Lock"]
        for pub_name,mod_name in meanings.items():
            if mod_name in DEFAULT_MODIFIER_NUISANCE or pub_name in DEFAULT_MODIFIER_IGNORE_KEYNAMES:
                continue
            #just hope that xxx_L is mapped to the same modifier as xxx_R!
            if pub_name.endswith("_L") or pub_name.endswith("_R"):
                pub_name = pub_name[:-2]
            elif pub_name=="ISO_Level3_Shift":
                pub_name = "AltGr"
            if pub_name not in modifier_names:
                modifier_names[pub_name.lower()] = mod_name
            if pub_name.lower()=="control":
                #alias "control" to "ctrl" as it is often used:
                modifier_names["ctrl"] = mod_name
        log("parse_shortcuts: modifier names=%s", modifier_names)

        #figure out the default shortcut modifiers
        #accept "," or "+" as delimiter:
        shortcut_modifiers = self.shortcut_modifiers.lower().replace(",", "+").split("+")
        def mod_defaults():
            mods = ["meta", "shift"]
            if POSIX:
                #gnome intercepts too many of the Alt+Shift shortcuts,
                #so use control with gnome:
                if os.environ.get("XDG_CURRENT_DESKTOP")=="GNOME":
                    mods = ["control", "shift"]
            return mods
        if shortcut_modifiers==["auto"]:
            shortcut_modifiers = mod_defaults()
        elif shortcut_modifiers==["none"]:
            shortcut_modifiers = []
        else:
            r = []
            for x in shortcut_modifiers:
                x = x.lower()
                if x not in modifier_names:
                    log.warn("Warning: invalid shortcut modifier '%s'", x)
                else:
                    r.append(x)
            if shortcut_modifiers and not r:
                log.warn(" using defaults instead")
                shortcut_modifiers = mod_defaults()
            else:
                shortcut_modifiers = r
        log("shortcut modifiers=%s", shortcut_modifiers)

        for s in strs:
            #example for s: Control+F8:some_action()
            parts = s.split(":", 1)
            if len(parts)!=2:
                log.error("Error: invalid key shortcut '%s'", s)
                continue
            #example for action: "quit"
            action = parts[1].strip()
            args = ()
            if action.find("(")>0 and action.endswith(")"):
                try:
                    action, all_args = action[:-1].split("(", 1)
                    args = []
                    for x in all_args.split(","):
                        x = x.strip()
                        if not x:
                            continue
                        if (x[0]=='"' and x[-1]=='"') or (x[0]=="'" and x[-1]=="'"):
                            args.append(x[1:-1])
                        if x=="None":
                            args.append(None)
                        if x.find("."):
                            args.append(float(x))
                        else:
                            args.append(int(x))
                    args = tuple(args)
                except Exception as e:
                    log.warn("Warning: failed to parse arguments of shortcut:")
                    log.warn(" '%s': %s", s, e)
                    continue
            action = action.replace("-", "_")       #must be an object attribute
            log("action(%s)=%s%s", s, action, args)

            #example for keyspec: ["Alt", "F8"]
            keyspec = parts[0].split("+")
            modifiers = []
            if len(keyspec)>1:
                valid = True
                #ie: ["Alt"]
                for mod in keyspec[:len(keyspec)-1]:
                    mod = mod.lower()
                    if mod=="none":
                        continue
                    elif mod=="#":
                        #this is the placeholder for the list of shortcut modifiers:
                        for x in shortcut_modifiers:
                            imod = modifier_names.get(x)
                            if imod:
                                modifiers.append(imod)
                        continue
                    #find the real modifier for this name:
                    #ie: "alt_l" -> "mod1"
                    imod = modifier_names.get(mod)
                    if not imod:
                        log.warn("Warning: invalid modifier '%s' in keyboard shortcut '%s'", mod, s)
                        log.warn(" the modifiers must be one of: %s", csv(modifier_names.keys()))
                        valid = False
                        break
                    modifiers.append(imod)
                if not valid:
                    continue
            #should we be validating the keyname?
            keyname = keyspec[len(keyspec)-1]
            shortcuts.setdefault(keyname, []).append((modifiers, action, args))
            log("shortcut(%s)=%s", s, csv((modifiers, action, args)))
        log("parse_shortcuts(%s)=%s" % (str(strs), shortcuts))
        print_nested_dict(shortcuts, print_fn=log)
        return shortcuts

    def key_handled_as_shortcut(self, window, key_name, modifiers, depressed):
        #find the shortcuts that may match this key:
        shortcuts = self.key_shortcuts.get(key_name)
        log("key_handled_as_shortcut: shortcut(%s)=%s", key_name, shortcuts)
        if not shortcuts:
            return False
        if len(shortcuts)>1:
            #sort shortcuts based on how many modifiers are required,
            #so that if multiple shortcuts use the same key,
            #we will try to match the one with the most modifiers first.
            #ie: Num_Lock+Menu will be tested before Menu
            #(this is needed because Num_Lock is then discarded when comparing the list of required modifiers!)
            shortcuts = sorted(shortcuts, key=lambda x : len(x[0]), reverse=True)
        for shortcut in shortcuts:
            if self._check_shortcut(window, key_name, modifiers, depressed, shortcut):
                return True
        return False

    def _check_shortcut(self, window, key_name, modifiers, depressed, shortcut):
        req_mods, action, args = shortcut
        extra_modifiers = list(modifiers)
        for rm in req_mods:
            if rm not in modifiers:
                #modifier is missing, bail out
                return False
            try:
                extra_modifiers.remove(rm)
            except ValueError:
                pass        #same modifier listed twice?
        kmod = self.keyboard.get_keymap_modifiers()[0]
        if not kmod and self.keyboard.modifier_keys:
            #fallback to server supplied map:
            kmod = self.keyboard.modifier_keys
        #ie: {'ISO_Level3_Shift': 'mod5', 'Meta_L': 'mod1', ...}
        log("keymap modifiers: %s", kmod)
        ignoremod = ("Caps_Lock", "Num_Lock")
        for x in ignoremod:
            mod = kmod.get(x)
            if mod in extra_modifiers:
                extra_modifiers.remove(mod)
        if extra_modifiers:
            log("skipping partial shortcut match %s, modifiers unmatched: %s", shortcut, extra_modifiers)
            return False
        log("matched shortcut %s", shortcut)
        if not depressed:
            #when the key is released, just ignore it - do NOT send it to the server!
            return True
        try:
            method = getattr(window, action)
            log("key_handled_as_shortcut(%s,%s,%s,%s) found shortcut=%s, will call %s%s",
                window, key_name, modifiers, depressed, shortcut, method, args)
        except AttributeError as e:
            log.error("key dropped, invalid method name in shortcut %s: %s", action, e)
            return True
        try:
            method(*args)
            log("key_handled_as_shortcut(%s,%s,%s,%s) has been handled: %s",
                window, key_name, modifiers, depressed, method)
        except Exception as e:
            log.error("key_handled_as_shortcut(%s,%s,%s,%s)", window, key_name, modifiers, depressed)
            log.error(" failed to execute shortcut=%s", shortcut)
            log.error("", exc_info=True)
        return  True


    def handle_key_action(self, window, wid, key_event):
        """
            Intercept key shortcuts and gives the Keyboard class
            a chance to fire more than one send_key_action.
            (win32 uses this for AltGr emulation)
        """
        if self.key_handled_as_shortcut(window, key_event.keyname, key_event.modifiers, key_event.pressed):
            return
        self.keyboard.process_key_event(self.send_key_action, wid, key_event)

    def send_key_action(self, wid, key_event):
        log("send_key_action(%s, %s)", wid, key_event)
        packet = ["key-action", wid]
        for x in ("keyname", "pressed", "modifiers", "keyval", "string", "keycode", "group"):
            packet.append(getattr(key_event, x))
        self.send(*packet)


    def get_layout_spec(self):
        """ add / honour overrides """
        layout, layouts, variant, variants, options = self.keyboard.get_layout_spec()
        log("%s.get_layout_spec()=%s", self.keyboard, (layout, layouts, variant, variants, options))
        def inl(v, l):
            try:
                if v in l or v is None:
                    return l
                return [v]+list(l)
            except Exception:
                if v is not None:
                    return [v]
                return []
        layout   = self.layout_option or layout
        layouts  = inl(layout, self.layouts_option or layouts)
        variant  = self.variant_option or variant
        variants = inl(variant, self.variants_option or variants)
        options  = self.options or options
        val = (layout, layouts, self.variant_option or variant, self.variants_option or variants, self.options)
        log("get_layout_spec()=%s", val)
        return val

    def get_keymap_spec(self):
        _print, query, query_struct = self.keyboard.get_keymap_spec()
        if query_struct:
            if self.layout_option:
                query_struct["layout"] = self.layout_option
            if self.layouts_option:
                query_struct["layouts"] = csv(self.layouts_option)
            if self.variant_option:
                query_struct["variant"] = self.variant_option
            if self.variants_option:
                query_struct["variants"] = csv(self.variants_option)
            if self.options:
                if self.options.lower()=="none":
                    query_struct["options"] = ""
                else:
                    query_struct["options"] = self.options
            if self.layout_option or self.layouts_option or self.variant_option or self.variants_option or self.options:
                from xpra.keyboard.layouts import xkbmap_query_tostring
                query = xkbmap_query_tostring(query_struct)
        return _print, query, query_struct

    def query_xkbmap(self):
        log("query_xkbmap()")
        (
            self.xkbmap_layout, self.xkbmap_layouts,
            self.xkbmap_variant, self.xkbmap_variants,
            self.xkbmap_options,
            ) = self.get_layout_spec()
        spec = self.get_keymap_spec()
        self.xkbmap_print, self.xkbmap_query, self.xkbmap_query_struct = spec
        log("query_xkbmap() get_keymap_spec()=%s", spec)
        self.xkbmap_keycodes = self.get_full_keymap()
        log("query_xkbmap() get_full_keymap()=%s", self.xkbmap_keycodes)
        self.xkbmap_x11_keycodes = self.keyboard.get_x11_keymap()
        log("query_xkbmap() %s.get_x11_keymap()=%s", self.keyboard, self.xkbmap_x11_keycodes)
        mods = self.keyboard.get_keymap_modifiers()
        (
            self.xkbmap_mod_meanings,
            self.xkbmap_mod_managed,
            self.xkbmap_mod_pointermissing,
            ) = mods
        log("query_xkbmap() %s.get_keymap_modifiers()=%s", self.keyboard, mods)
        self.update_hash()
        log("layout=%s, layouts=%s, variant=%s, variants=%s",
            self.xkbmap_layout, self.xkbmap_layouts, self.xkbmap_variant, self.xkbmap_variants)
        log("print=%s, query=%s, struct=%s", nonl(self.xkbmap_print), nonl(self.xkbmap_query), self.xkbmap_query_struct)
        log("keycodes=%s", repr_ellipsized(str(self.xkbmap_keycodes)))
        log("x11 keycodes=%s", repr_ellipsized(str(self.xkbmap_x11_keycodes)))
        log("mod managed: %s", self.xkbmap_mod_managed)
        log("mod meanings: %s", self.xkbmap_mod_meanings)
        log("mod pointermissing: %s", self.xkbmap_mod_pointermissing)
        log("hash=%s", self.hash)

    def update(self):
        if not self.locked:
            self.query_xkbmap()

    def layout_str(self):
        return " / ".join([bytestostr(x) for x in (
            self.layout_option or self.xkbmap_layout, self.variant_option or self.xkbmap_variant) if bool(x)])


    def send_layout(self):
        log("send_layout() layout_option=%s, xkbmap_layout=%s, variant_option=%s, xkbmap_variant=%s, xkbmap_options=%s",
            self.layout_option, self.xkbmap_layout, self.variant_option, self.xkbmap_variant, self.xkbmap_options)
        self.send("layout-changed",
                  self.layout_option or self.xkbmap_layout or "",
                  self.variant_option or self.xkbmap_variant or "",
                  self.xkbmap_options or "")

    def send_keymap(self):
        log("send_keymap()")
        self.send("keymap-changed", self.get_keymap_properties())


    def update_hash(self):
        import hashlib
        h = hashlib.sha1()
        def hashadd(v):
            h.update(("/%s" % str(v)).encode("utf8"))
        for x in (self.xkbmap_print, self.xkbmap_query, \
                  self.xkbmap_mod_meanings, self.xkbmap_mod_pointermissing, \
                  self.xkbmap_keycodes, self.xkbmap_x11_keycodes):
            hashadd(x)
        if self.xkbmap_query_struct:
            #flatten the dict in a predicatable order:
            for k in sorted(self.xkbmap_query_struct.keys()):
                hashadd(self.xkbmap_query_struct.get(k))
        self.hash = "/".join([str(x) for x in (self.xkbmap_layout, self.xkbmap_variant, h.hexdigest()) if bool(x)])

    def get_full_keymap(self):
        return []


    def get_keymap_properties(self):
        props = {}
        for x in ("layout", "layouts", "variant", "variants",
                  "raw", "layout_groups",
                  "print", "query", "query_struct", "mod_meanings",
                  "mod_managed", "mod_pointermissing", "keycodes", "x11_keycodes"):
            p = "xkbmap_%s" % x
            v = getattr(self, p)
            #replace None with empty string:
            if v is None:
                v = ""
            props[p] = v
        return  props


    def log_keyboard_info(self):
        #show the user a summary of what we have detected:
        kb_info = {}
        if self.xkbmap_query_struct or self.xkbmap_query:
            xkbqs = self.xkbmap_query_struct
            if not xkbqs:
                #parse query into a dict
                from xpra.keyboard.layouts import parse_xkbmap_query
                xkbqs = parse_xkbmap_query(self.xkbmap_query)
            for x in ("rules", "model", "layout"):
                v = xkbqs.get(x)
                if v:
                    kb_info[x] = v
        if self.xkbmap_layout:
            kb_info["layout"] = self.xkbmap_layout
        if not kb_info:
            log.info(" using default keyboard settings")
        else:
            log.info(" keyboard settings: %s", csv("%s=%s" % (std(k), std(v)) for k,v in kb_info.items()))
