# This file is part of Xpra.
# Copyright (C) 2010 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2011-2015 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.util import nonl
from xpra.platform.keyboard_base import KeyboardBase
from xpra.keyboard.mask import MODIFIER_MAP
from xpra.keyboard.layouts import xkbmap_query_tostring
from xpra.log import Logger
log = Logger("keyboard", "posix")


class Keyboard(KeyboardBase):

    def __init__(self):
        KeyboardBase.__init__(self)
        self.keymap_modifiers = None
        try:
            from xpra.x11.bindings.keyboard_bindings import X11KeyboardBindings   #@UnresolvedImport
            self.keyboard_bindings = X11KeyboardBindings()
        except Exception as e:
            log.warn("failed load posix keyboard bindings: %s", e)
            self.keyboard_bindings = None


    def get_keymap_modifiers(self):
        if self.keymap_modifiers is None:
            self.keymap_modifiers = self.do_get_keymap_modifiers()
        return self.keymap_modifiers

    def do_get_keymap_modifiers(self):
        if not self.keyboard_bindings:
            log.warn("keyboard bindings are not available, expect keyboard mapping problems")
            return {}, [], []
        try:
            mod_mappings = self.keyboard_bindings.get_modifier_mappings()
            if mod_mappings:
                #ie: {"shift" : ["Shift_L", "Shift_R"], "mod1" : "Meta_L", ...]}
                log("modifier mappings=%s", mod_mappings)
                meanings = {}
                for modifier,keys in mod_mappings.items():
                    for _,keyname in keys:
                        meanings[keyname] = modifier
                #probably a GTK bug? but easier to put here
                mod_missing = []
                numlock_mod = meanings.get("Num_Lock", [])
                if numlock_mod:
                    mod_missing.append(numlock_mod)
                return  meanings, [], mod_missing
        except Exception as e:
            log.error("failed to use native get_modifier_mappings: %s", e, exc_info=True)

    def get_x11_keymap(self):
        if not self.keyboard_bindings:
            return  {}
        try:
            return self.keyboard_bindings.get_keycode_mappings()
        except Exception as e:
            log.error("failed to use raw x11 keymap: %s", e)


    def get_keymap_spec(self):
        log("get_keymap_spec() keyboard_bindings=%s", self.keyboard_bindings)
        if not self.keyboard_bindings:
            return None
        _query_struct = self.keyboard_bindings.getXkbProperties()
        _query = xkbmap_query_tostring(_query_struct)
        log("get_keymap_spec() Xkb query tostring(%s)=%s", _query_struct, _query)
        #we no longer support servers via xkbmap_print:
        xkbmap_print = ""
        log("get_keymap_spec()=(%s, %s, %s)", nonl(xkbmap_print), nonl(_query), nonl(_query_struct))
        return xkbmap_print, _query, _query_struct


    def get_xkb_rules_names_property(self):
        #parses the "_XKB_RULES_NAMES" X11 property
        #FIXME: a bit ugly to call gtk here...
        #but otherwise we have to call XGetWindowProperty and deal with X11 errors..
        xkb_rules_names = ""
        from xpra.platform.xposix.gui import _get_X11_root_property
        prop = _get_X11_root_property("_XKB_RULES_NAMES", "STRING")
        log("get_xkb_rules_names_property() _XKB_RULES_NAMES=%s", prop)
        #ie: 'evdev\x00pc104\x00gb,us\x00,\x00\x00'
        if prop:
            xkb_rules_names = prop.split("\0")
            #ie: ['evdev', 'pc104', 'gb,us', ',', '', '']
        log("get_xkb_rules_names_property()=%s", xkb_rules_names)
        return xkb_rules_names

    def get_layout_spec(self):
        layout = ""
        layouts = []
        v = None
        if self.keyboard_bindings:
            v = self.keyboard_bindings.getXkbProperties().get("layout")
        if not v:
            #fallback:
            v = self.get_xkb_rules_names_property()
            #ie: ['evdev', 'pc104', 'gb,us', ',', '', '']
            if v and len(v)>=3:
                v = v[2]
        if v:
            layouts = v.split(",")
            layout = v
        def s(v):
            try:
                return v.decode("latin1")
            except:
                return str(v)
        return s(layout), [s(x) for x in layouts], "", None


    def get_keyboard_repeat(self):
        v = None
        if self.keyboard_bindings:
            try:
                v = self.keyboard_bindings.get_key_repeat_rate()
                if v:
                    assert len(v)==2
            except Exception as e:
                log.error("Error: failed to get keyboard repeat rate:")
                log.error(" %s", e)
                v = None
        log("get_keyboard_repeat()=%s", v)
        return v

    def update_modifier_map(self, display, xkbmap_mod_meanings):
        try:
            from xpra.x11.gtk_x11.keys import grok_modifier_map
            self.modifier_map = grok_modifier_map(display, xkbmap_mod_meanings)
        except ImportError:
            self.modifier_map = MODIFIER_MAP
        #force re-query on next call:
        self.keymap_modifiers = None
        try:
            dn = "%s %s" % (type(display).__name__, display.get_name())
        except:
            dn = str(display)
        log("update_modifier_map(%s, %s) modifier_map=%s", dn, xkbmap_mod_meanings, self.modifier_map)
