# This file is part of Xpra.
# Copyright (C) 2010 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2011-2013 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.


from xpra.platform.keyboard_base import KeyboardBase
from xpra.keyboard.mask import MODIFIER_MAP
from xpra.log import Logger
log = Logger()


class Keyboard(KeyboardBase):

    def exec_get_keyboard_data(self, cmd):
        # Find the client's current keymap so we can send it to the server:
        try:
            from xpra.scripts.exec_util import safe_exec
            returncode, out, _ = safe_exec(cmd)
            if returncode==0:
                return out.decode('utf-8')
            log.error("'%s' failed with exit code %s", cmd, returncode)
        except Exception, e:
            log.error("error running '%s': %s", cmd, e)
        return None

    def get_keymap_modifiers(self):
        try:
            from xpra.x11.lowlevel import get_modifier_mappings         #@UnresolvedImport
            mod_mappings = get_modifier_mappings()
            if mod_mappings:
                #ie: {"shift" : ["Shift_L", "Shift_R"], "mod1" : "Meta_L", ...]}
                log.debug("modifier mappings=%s", mod_mappings)
                meanings = {}
                for modifier,keys in mod_mappings.items():
                    for _,keyname in keys:
                        meanings[keyname] = modifier
                return  meanings, [], []
        except ImportError, e:
            log.error("failed to use native get_modifier_mappings: %s", e)
        except Exception, e:
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
        log.debug("get_keymap_modifiers parsed: meanings=%s", meanings)
        return  meanings, [], []

    def get_x11_keymap(self):
        try:
            from xpra.gtk_common.gobject_compat import import_gdk
            gdk = import_gdk()
            _display = gdk.get_display()
            assert _display, "cannot open the display with GTK, is DISPLAY set?"
            from xpra.x11.lowlevel import get_keycode_mappings      #@UnresolvedImport
            return get_keycode_mappings(gdk.get_default_root_window())
        except Exception, e:
            log.error("failed to use raw x11 keymap: %s", e)
        return  {}

    def get_keymap_spec(self):
        xkbmap_print = self.exec_get_keyboard_data(["setxkbmap", "-print"])
        if xkbmap_print is None:
            log.error("your keyboard mapping will probably be incorrect unless you are using a 'us' layout");
        xkbmap_query = self.exec_get_keyboard_data(["setxkbmap", "-query"])
        if xkbmap_query is None and xkbmap_print is not None:
            log.error("the server will try to guess your keyboard mapping, which works reasonably well in most cases");
            log.error("however, upgrading 'setxkbmap' to a version that supports the '-query' parameter is preferred");
        return xkbmap_print, xkbmap_query

    def get_keyboard_repeat(self):
        try:
            from xpra.x11.lowlevel import get_key_repeat_rate   #@UnresolvedImport
            delay, interval = get_key_repeat_rate()
            return delay,interval
        except Exception, e:
            log.error("failed to get keyboard repeat rate: %s", e)
        return None

    def update_modifier_map(self, display_source, xkbmap_mod_meanings):
        try:
            from xpra.x11.gtk_x11.keys import grok_modifier_map
            self.modifier_map = grok_modifier_map(display_source, xkbmap_mod_meanings)
        except ImportError:
            self.modifier_map = MODIFIER_MAP
