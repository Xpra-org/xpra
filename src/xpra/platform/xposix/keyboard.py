# This file is part of Xpra.
# Copyright (C) 2010 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2011-2014 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.platform.keyboard_base import KeyboardBase
from xpra.keyboard.mask import MODIFIER_MAP
from xpra.keyboard.layouts import parse_xkbmap_query, xkbmap_query_tostring
from xpra.log import Logger
log = Logger("keyboard", "posix")

try:
    from xpra.x11.bindings.keyboard_bindings import X11KeyboardBindings   #@UnresolvedImport
    keyboard_bindings = X11KeyboardBindings()
except Exception as e:
    log.warn("failed load posix keyboard bindings: %s", e)
    keyboard_bindings = None


class Keyboard(KeyboardBase):

    def exec_get_keyboard_data(self, cmd):
        # Find the client's current keymap so we can send it to the server:
        try:
            from xpra.scripts.exec_util import safe_exec
            returncode, out, _ = safe_exec(cmd)
            if returncode==0:
                return out.decode('utf-8')
            log.error("'%s' failed with exit code %s", cmd, returncode)
        except Exception as e:
            log.error("error running '%s': %s", cmd, e)
        return None

    def get_keymap_modifiers(self):
        if keyboard_bindings:
            try:
                mod_mappings = keyboard_bindings.get_modifier_mappings()
                if mod_mappings:
                    #ie: {"shift" : ["Shift_L", "Shift_R"], "mod1" : "Meta_L", ...]}
                    log("modifier mappings=%s", mod_mappings)
                    meanings = {}
                    for modifier,keys in mod_mappings.items():
                        for _,keyname in keys:
                            meanings[keyname] = modifier
                    return  meanings, [], []
            except Exception as e:
                log.error("failed to use native get_modifier_mappings: %s", e, exc_info=True)
        return self.modifiers_fallback()

    def modifiers_fallback(self):
        xmodmap_pm = self.exec_get_keyboard_data(["xmodmap", "-pm"])
        if not xmodmap_pm:
            log.warn("bindings are not available and 'xmodmap -pm' also failed, expect keyboard mapping problems")
            return {}, [], []
        #parse it so we can feed it back to xmodmap (ala "xmodmap -pke")
        meanings = {}
        for line in xmodmap_pm.splitlines()[1:]:
            if not line:
                continue
            parts = line.split()
            #ie: ['shift', 'Shift_L', '(0x32),', 'Shift_R', '(0x3e)']
            if len(parts)>1:
                nohex = [x for x in parts[1:] if not x.startswith("(")]
                for x in nohex:
                    #ie: meanings['Shift_L']=shift
                    meanings[x] = parts[0]
        log("get_keymap_modifiers parsed: meanings=%s", meanings)
        return  meanings, [], []

    def get_x11_keymap(self):
        if keyboard_bindings:
            try:
                return keyboard_bindings.get_keycode_mappings()
            except Exception as e:
                log.error("failed to use raw x11 keymap: %s", e)
        return  {}


    def get_keymap_spec_using_setxkbmap(self):
        xkbmap_print = self.exec_get_keyboard_data(["setxkbmap", "-print"])
        if xkbmap_print is None:
            log.error("your keyboard mapping will probably be incorrect unless you are using a 'us' layout")
        xkbmap_query = self.exec_get_keyboard_data(["setxkbmap", "-query"])
        if xkbmap_query is None and xkbmap_print is not None:
            log.error("the server will try to guess your keyboard mapping, which works reasonably well in most cases")
            log.error("however, upgrading 'setxkbmap' to a version that supports the '-query' parameter is preferred")
            xkbmap_query_struct = parse_xkbmap_query(xkbmap_query)
        else:
            xkbmap_query_struct = {}
        return xkbmap_print, xkbmap_query, xkbmap_query_struct

    def get_keymap_spec_from_xkb(self):
        log("get_keymap_spec_from_xkb() keyboard_bindings=%s", keyboard_bindings)
        if not keyboard_bindings:
            return None
        _query_struct = keyboard_bindings.getXkbProperties()
        _query = xkbmap_query_tostring(_query_struct)
        return "", _query, _query_struct

    def get_keymap_spec(self):
        v = self.get_keymap_spec_from_xkb()
        if not v:
            v = self.get_keymap_spec_using_setxkbmap()
        from xpra.util import nonl
        log("get_keymap_spec()=%s", nonl(str(v)))
        return v


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
        if keyboard_bindings:
            v = keyboard_bindings.getXkbProperties().get("layout")
        if not v:
            #fallback:
            v = self.get_xkb_rules_names_property()
            #ie: ['evdev', 'pc104', 'gb,us', ',', '', '']
            if v and len(v)>=3:
                v = v[2]
        if v:
            layouts = v.split(",")
            layout = v
        return layout, layouts, "", None


    def get_keyboard_repeat(self):
        if keyboard_bindings:
            try:
                delay, interval = keyboard_bindings.get_key_repeat_rate()
                return delay,interval
            except Exception as e:
                log.error("failed to get keyboard repeat rate: %s", e)
        return None

    def update_modifier_map(self, display, xkbmap_mod_meanings):
        try:
            dn = "%s %s" % (type(display).__name__, display.get_name())
        except Exception as e:
            dn = str(display)
        try:
            from xpra.x11.gtk_x11.keys import grok_modifier_map
            self.modifier_map = grok_modifier_map(display, xkbmap_mod_meanings)
        except ImportError:
            self.modifier_map = MODIFIER_MAP
        log("update_modifier_map(%s, %s) modifier_map=%s", dn, xkbmap_mod_meanings, self.modifier_map)
