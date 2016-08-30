# This file is part of Xpra.
# Copyright (C) 2011 Serviware (Arthur Huillet, <ahuillet@serviware.com>)
# Copyright (C) 2010-2014 Antoine Martin <antoine@devloop.org.uk>
# Copyright (C) 2008, 2010 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.log import Logger
log = Logger("keyboard")

from xpra.keyboard.layouts import xkbmap_query_tostring
from xpra.keyboard.mask import DEFAULT_MODIFIER_MEANINGS, DEFAULT_MODIFIER_NUISANCE
from xpra.util import nonl, csv, std, print_nested_dict


class KeyboardHelper(object):

    def __init__(self, net_send, keyboard_sync, key_shortcuts, raw, layout, layouts, variant, variants, options):
        self.reset_state()
        self.send = net_send
        self.locked = False
        self.keyboard_sync = keyboard_sync
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
        self.keyboard = Keyboard()
        log("KeyboardHelper(%s) keyboard=%s", (net_send, keyboard_sync, key_shortcuts, raw, layout, layouts, variant, variants, options), self.keyboard)

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
        self.xkbmap_print = ""
        self.xkbmap_query = ""
        self.xkbmap_query_struct = {}

        self.hash = None

        self.key_repeat_delay = -1
        self.key_repeat_interval = -1
        self.keys_pressed = {}
        self.keyboard_sync = False
        self.key_shortcuts = {}

    def cleanup(self):
        self.clear_repeat()
        self.reset_state()
        def nosend(*args):
            pass
        self.send = nosend

    def keymap_changed(self, *args):
        pass


    def parse_shortcuts(self, strs):
        #TODO: maybe parse with re instead?
        if len(strs)==0:
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

        for s in strs:
            #example for s: Control+F8:some_action()
            parts = s.split(":", 1)
            if len(parts)!=2:
                log.error("Error: invalid key shortcut '%s'", s)
                continue
            #example for action: "quit"
            action = parts[1]
            args = ()
            if action.find("(")>0 and action.endswith(")"):
                try:
                    action, all_args = action[:-1].split("(", 1)
                    args = []
                    for x in all_args.split(","):
                        x = x.strip()
                        if len(x)==0:
                            continue
                        if (x[0]=='"' and x[-1]=='"') or (x[0]=="'" and x[-1]=="'"):
                            args.append(x[1:-1])
                        elif x=="None":
                            args.append(None)
                        elif x.find("."):
                            args.append(float(x))
                        else:
                            args.append(int(x))
                    args = tuple(args)
                except Exception as e:
                    log.warn("failed to parse arguments of shortcut '%s': %s", s, e)
                    continue
            log("action(%s)=%s%s", s, action, args)

            #example for keyspec: ["Alt", "F8"]
            keyspec = parts[0].split("+")
            modifiers = []
            if len(keyspec)>1:
                valid = True
                #ie: ["Alt"]
                for mod in keyspec[:len(keyspec)-1]:
                    #ie: "alt_l" -> "mod1"
                    imod = modifier_names.get(mod.lower())
                    if not imod:
                        log.error("Error: invalid modifier '%s' in keyboard shortcut '%s'", mod, s)
                        log.error(" the modifiers must be one of: %s", csv(modifier_names.keys()))
                        valid = False
                        break
                    modifiers.append(imod)
                if not valid:
                    continue
            #TODO: validate keyname
            keyname = keyspec[len(keyspec)-1]
            shortcuts.setdefault(keyname, []).append((modifiers, action, args))
            log("shortcut(%s)=%s", keyname, (modifiers, action, args))
        log("parse_shortcuts(%s)=%s" % (str(strs), shortcuts))
        print_nested_dict(shortcuts, print_fn=log)
        return  shortcuts

    def key_handled_as_shortcut(self, window, key_name, modifiers, depressed):
        #find the shortcuts that may match this key:
        shortcuts = self.key_shortcuts.get(key_name)
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
        (req_mods, action, args) = shortcut
        extra_modifiers = list(modifiers)
        for rm in req_mods:
            if rm not in modifiers:
                #modifier is missing, bail out
                return False
            try:
                extra_modifiers.remove(rm)
            except:
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
            """ when the key is released, just ignore it - do NOT send it to the server! """
            return True
        try:
            method = getattr(window, action)
            log("key_handled_as_shortcut(%s,%s,%s,%s) found shortcut=%s, will call %s%s", window, key_name, modifiers, depressed, shortcut, method, args)
        except AttributeError as e:
            log.error("key dropped, invalid method name in shortcut %s: %s", action, e)
            return True
        try:
            method(*args)
            log("key_handled_as_shortcut(%s,%s,%s,%s) has been handled: %s", window, key_name, modifiers, depressed, method)
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
        if self.keyboard_sync and self.key_repeat_delay>0 and self.key_repeat_interval>0:
            self._key_repeat(key_event)

    def _key_repeat(self, key_event):
        """ this method takes care of scheduling the sending of
            "key-repeat" packets to the server so that it can
            maintain a consistent keyboard state.
        """
        wid, keyname, pressed, _, keyval, _, keycode, _ = key_event
        #we keep track of which keys are still pressed in a dict,
        if keycode<0:
            key = keyname
        else:
            key = keycode
        if not pressed and key in self.keys_pressed:
            """ stop the timer and clear this keycode: """
            timer = self.keys_pressed[key]
            log("key repeat: clearing timer %s for %s / %s", timer, keyname, keycode)
            self.source_remove(timer)
            del self.keys_pressed[key]
        elif pressed and key not in self.keys_pressed:
            """ we must send packets to the server regularly for as long as the key is still pressed: """
            #TODO: we can have latency measurements (see ping).. use them?
            LATENCY_JITTER = 100
            MIN_DELAY = 5
            delay = max(self.key_repeat_delay-LATENCY_JITTER, MIN_DELAY)
            interval = max(self.key_repeat_interval-LATENCY_JITTER, MIN_DELAY)
            log("scheduling key repeat for %s: delay=%s, interval=%s (from %s and %s)", keyname, delay, interval, self.key_repeat_delay, self.key_repeat_interval)
            def send_key_repeat():
                modifiers = self.get_current_modifiers()
                self.send_now("key-repeat", wid, keyname, keyval, keycode, modifiers)
            def continue_key_repeat(*args):
                #if the key is still pressed (redundant check?)
                #confirm it and continue, otherwise stop
                log("continue_key_repeat for %s / %s", keyname, keycode)
                if key in self.keys_pressed:
                    send_key_repeat()
                    return  True
                else:
                    del self.keys_pressed[key]
                    return  False
            def start_key_repeat(*args):
                #if the key is still pressed (redundant check?)
                #confirm it and start repeat:
                log("start_key_repeat for %s / %s", keyname, keycode)
                if key in self.keys_pressed:
                    send_key_repeat()
                    self.keys_pressed[key] = self.timeout_add(interval, continue_key_repeat)
                else:
                    del self.keys_pressed[key]
                return  False   #never run this timer again
            log("key repeat: starting timer for %s / %s with delay %s and interval %s", keyname, keycode, delay, interval)
            self.keys_pressed[key] = self.timeout_add(delay, start_key_repeat)

    def clear_repeat(self):
        for timer in self.keys_pressed.values():
            self.source_remove(timer)
        self.keys_pressed = {}


    def get_layout_spec(self):
        """ add / honour overrides """
        layout, layouts, variant, variants = self.keyboard.get_layout_spec()
        log("%s.get_layout_spec()=%s", self.keyboard, (layout, layouts, variant, variants))
        def inl(v, l):
            try:
                if v in l or v is None:
                    return l
                return [v]+list(l)
            except:
                if v is not None:
                    return [v]
                return []
        layout   = self.layout_option or layout
        layouts  = inl(layout, self.layouts_option or layouts)
        variant  = self.variant_option or variant
        variants = inl(variant, self.variants_option or variants)
        return layout, layouts, self.variant_option or variant, self.variants_option or variants

    def get_keymap_spec(self):
        _print, query, query_struct = self.keyboard.get_keymap_spec()
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
            query = xkbmap_query_tostring(query_struct)
        return _print, query, query_struct

    def query_xkbmap(self):
        self.xkbmap_layout, self.xkbmap_layouts, self.xkbmap_variant, self.xkbmap_variants = self.get_layout_spec()
        self.xkbmap_print, self.xkbmap_query, self.xkbmap_query_struct = self.get_keymap_spec()
        self.xkbmap_keycodes = self.get_full_keymap()
        self.xkbmap_x11_keycodes = self.keyboard.get_x11_keymap()
        self.xkbmap_mod_meanings, self.xkbmap_mod_managed, self.xkbmap_mod_pointermissing = self.keyboard.get_keymap_modifiers()
        self.update_hash()
        log("layout=%s, layouts=%s, variant=%s, variants=%s", self.xkbmap_layout, self.xkbmap_layouts, self.xkbmap_variant, self.xkbmap_variants)
        log("print=%s, query=%s, struct=%s", nonl(self.xkbmap_print), nonl(self.xkbmap_query), nonl(self.xkbmap_query_struct))
        log("keycodes=%s", str(self.xkbmap_keycodes)[:80]+"...")
        log("x11 keycodes=%s", str(self.xkbmap_x11_keycodes)[:80]+"...")
        log("mod managed: %s", self.xkbmap_mod_managed)
        log("mod meanings: %s", self.xkbmap_mod_meanings)
        log("mod pointermissing: %s", self.xkbmap_mod_pointermissing)
        log("hash=%s", self.hash)

    def update(self):
        if not self.locked:
            self.query_xkbmap()

    def layout_str(self):
        return " / ".join([x for x in (self.layout_option or self.xkbmap_layout, self.variant_option or self.xkbmap_variant) if bool(x)])


    def send_layout(self):
        log("send_layout()")
        self.send("layout-changed", self.layout_option or self.xkbmap_layout or "", self.variant_option or self.xkbmap_variant or "")

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
                  "raw",
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
            if xkbqs:
                #parse query into a dict
                from xpra.keyboard.layouts import parse_xkbmap_query
                xkbqs = parse_xkbmap_query(self.xkbmap_query)
            for x in ["rules", "model", "layout"]:
                v = xkbqs.get(x)
                if v:
                    kb_info[x] = v
        if self.xkbmap_layout:
            kb_info["layout"] = self.xkbmap_layout
        if len(kb_info)==0:
            log.info(" using default keyboard settings")
        else:
            log.info(" keyboard settings: %s", ", ".join(["%s=%s" % (std(k), std(v)) for k,v in kb_info.items()]))
