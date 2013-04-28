# This file is part of Xpra.
# Copyright (C) 2011 Serviware (Arthur Huillet, <ahuillet@serviware.com>)
# Copyright (C) 2010-2013 Antoine Martin <antoine@devloop.org.uk>
# Copyright (C) 2008, 2010 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.log import Logger
log = Logger()

from xpra.keyboard.mask import DEFAULT_MODIFIER_MEANINGS, DEFAULT_MODIFIER_NUISANCE
from xpra.platform.keyboard import Keyboard

def nn(x):
    if x is None:
        return  ""
    return x


class KeyboardHelper(object):

    def __init__(self, net_send, keyboard_sync, key_shortcuts):
        self.reset_state()
        self.send = net_send
        self.keyboard_sync = keyboard_sync
        self.key_shortcuts = self.parse_shortcuts(key_shortcuts)
        self.keyboard = Keyboard()

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
        self.xkbmap_variant = ""
        self.xkbmap_variants = []
        self.xkbmap_print = ""
        self.xkbmap_query = ""

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


    def parse_shortcuts(self, strs):
        #TODO: maybe parse with re instead?
        if len(strs)==0:
            """ if none are defined, add this as default
            it would be nicer to specify it via OptionParser in main
            but then it would always have to be there with no way of removing it
            whereas now it is enough to define one (any shortcut)
            """
            strs = ["meta+shift+F4:quit"]
        log.debug("parse_shortcuts(%s)" % str(strs))
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

        for s in strs:
            #example for s: Control+F8:some_action()
            parts = s.split(":", 1)
            if len(parts)!=2:
                log.error("invalid shortcut: %s" % s)
                continue
            #example for action: "quit"
            action = parts[1]
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
                        log.error("invalid modifier: %s, valid modifiers are: %s", mod, modifier_names.keys())
                        valid = False
                        break
                    modifiers.append(imod)
                if not valid:
                    continue
            keyname = keyspec[len(keyspec)-1]
            shortcuts[keyname] = (modifiers, action)
        log.debug("parse_shortcuts(%s)=%s" % (str(strs), shortcuts))
        return  shortcuts

    def key_handled_as_shortcut(self, window, key_name, modifiers, depressed):
        shortcut = self.key_shortcuts.get(key_name)
        if not shortcut:
            return  False
        (req_mods, action) = shortcut
        for rm in req_mods:
            if rm not in modifiers:
                #modifier is missing, bail out
                return False
        if not depressed:
            """ when the key is released, just ignore it - do NOT send it to the server! """
            return  True
        try:
            method = getattr(window, action)
            log.info("key_handled_as_shortcut(%s,%s,%s,%s) has been handled by shortcut=%s", window, key_name, modifiers, depressed, shortcut)
        except AttributeError, e:
            log.error("key dropped, invalid method name in shortcut %s: %s", action, e)
            return  True
        try:
            method()
        except KeyboardInterrupt:
            raise
        except Exception, e:
            log.error("key_handled_as_shortcut(%s,%s,%s,%s) failed to execute shortcut=%s: %s", window, key_name, modifiers, depressed, shortcut, e)
        return  True


    def parse_key_event(self, wid, event, pressed):
        raise Exception("override me!")
        #return wid, keyname, pressed, modifiers, keyval, string, keycode, group

    def handle_key_action(self, event, window, wid, pressed):
        #NOTE: handle_key_event may fire send_key_action more than once (see win32 AltGr)
        key_event = self.parse_key_event(wid, event, pressed)
        keyname = key_event[1]
        modifiers = key_event[3]
        if self.key_handled_as_shortcut(window, keyname, modifiers, pressed):
            return
        self.keyboard.process_key_event(self.send_key_action, key_event)

    def send_key_action(self, key_event):
        log("send_key_action(%s)", key_event)
        self.send("key-action", *key_event)
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
            """ we must ping the server regularly for as long as the key is still pressed: """
            #TODO: we can have latency measurements (see ping).. use them?
            LATENCY_JITTER = 100
            MIN_DELAY = 5
            delay = max(self.key_repeat_delay-LATENCY_JITTER, MIN_DELAY)
            interval = max(self.key_repeat_interval-LATENCY_JITTER, MIN_DELAY)
            log.debug("scheduling key repeat for %s: delay=%s, interval=%s (from %s and %s)", keyname, delay, interval, self.key_repeat_delay, self.key_repeat_interval)
            def send_key_repeat():
                modifiers = self.get_current_modifiers()
                self.send_now("key-repeat", wid, keyname, keyval, keycode, modifiers)
            def continue_key_repeat(*args):
                #if the key is still pressed (redundant check?)
                #confirm it and continue, otherwise stop
                log.debug("continue_key_repeat for %s / %s", keyname, keycode)
                if key in self.keys_pressed:
                    send_key_repeat()
                    return  True
                else:
                    del self.keys_pressed[key]
                    return  False
            def start_key_repeat(*args):
                #if the key is still pressed (redundant check?)
                #confirm it and start repeat:
                log.debug("start_key_repeat for %s / %s", keyname, keycode)
                if key in self.keys_pressed:
                    send_key_repeat()
                    self.keys_pressed[key] = self.timeout_add(interval, continue_key_repeat)
                else:
                    del self.keys_pressed[key]
                return  False   #never run this timer again
            log.debug("key repeat: starting timer for %s / %s with delay %s and interval %s", keyname, keycode, delay, interval)
            self.keys_pressed[key] = self.timeout_add(delay, start_key_repeat)

    def clear_repeat(self):
        for timer in self.keys_pressed.values():
            self.source_remove(timer)
        self.keys_pressed = {}


    def query_xkbmap(self):
        self.xkbmap_layout, self.xkbmap_variant, self.xkbmap_variants = self.keyboard.get_layout_spec()
        self.xkbmap_print, self.xkbmap_query = self.keyboard.get_keymap_spec()
        self.xkbmap_keycodes = self.get_full_keymap()
        self.xkbmap_x11_keycodes = self.keyboard.get_x11_keymap()
        self.xkbmap_mod_meanings, self.xkbmap_mod_managed, self.xkbmap_mod_pointermissing = self.keyboard.get_keymap_modifiers()
        log.debug("layout=%s, variant=%s", self.xkbmap_layout, self.xkbmap_variant)
        log.debug("print=%s, query=%s", self.xkbmap_print, self.xkbmap_query)
        log.debug("keycodes=%s", str(self.xkbmap_keycodes)[:80]+"...")
        log.debug("x11 keycodes=%s", str(self.xkbmap_x11_keycodes)[:80]+"...")
        log.debug("xkbmap_mod_meanings: %s", self.xkbmap_mod_meanings)

    def get_full_keymap(self):
        return []


    def get_keymap_properties(self):
        props = {}
        for x in ["xkbmap_print", "xkbmap_query", "xkbmap_mod_meanings",
              "xkbmap_mod_managed", "xkbmap_mod_pointermissing", "xkbmap_keycodes", "xkbmap_x11_keycodes"]:
            props[x] = nn(getattr(self, x))
        return  props
