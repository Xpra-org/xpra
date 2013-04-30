# This file is part of Xpra.
# Copyright (C) 2010 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2011-2013 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.


from xpra.platform.keyboard_base import KeyboardBase
from xpra.keyboard.layouts import WIN32_LAYOUTS
from xpra.log import Logger
log = Logger()


class Keyboard(KeyboardBase):
    def __init__(self):
        KeyboardBase.__init__(self)
        self.emulate_altgr = False
        self.num_lock_modifier = None
        self.last_key_event_sent = None

    def set_modifier_mappings(self, mappings):
        KeyboardBase.set_modifier_mappings(self, mappings)
        self.num_lock_modifier = self.modifier_keys.get("Num_Lock")
        log("set_modifier_mappings found 'Num_Lock' modifier value: %s", self.num_lock_modifier)

    def mask_to_names(self, mask):
        """ Patch NUMLOCK and AltGr """
        names = KeyboardBase.mask_to_names(self, mask)
        if self.emulate_altgr:
            self.AltGr_modifiers(names)
        if self.num_lock_modifier:
            try:
                import win32api         #@UnresolvedImport
                import win32con         #@UnresolvedImport
                numlock = win32api.GetKeyState(win32con.VK_NUMLOCK)
                log("mask_to_names(%s) GetKeyState(VK_NUMLOCK)=%s", mask, numlock)
                if numlock and self.num_lock_modifier not in names:
                    names.append(self.num_lock_modifier)
                elif not numlock and self.num_lock_modifier in names:
                    names.remove(self.num_lock_modifier)
            except:
                pass
        log("mask_to_names(%s)=%s", mask, names)
        return names

    def AltGr_modifiers(self, modifiers, pressed=True):
        add = []
        clear = ["mod1", "mod2", "control"]
        if pressed:
            add.append("mod5")
        else:
            clear.append("mod5")
        log("AltGr_modifiers(%s, %s) add=%s, clear=%s", modifiers, pressed, add, clear)
        for x in add:
            if x not in modifiers:
                modifiers.append(x)
        for x in clear:
            if x in modifiers:
                modifiers.remove(x)

    def get_keymap_modifiers(self):
        """
            ask the server to manage numlock, and lock can be missing from mouse events
            (or maybe this is virtualbox causing it?)
        """
        return  {}, [], ["lock"]

    def get_layout_spec(self):
        layout = None
        variant = None
        variants = None
        try:
            import win32api         #@UnresolvedImport
            kbid = win32api.GetKeyboardLayout(0) & 0xffff
            if kbid in WIN32_LAYOUTS:
                code, _, _, _, layout, variants = WIN32_LAYOUTS.get(kbid)
                log.debug("found keyboard layout '%s' with variants=%s, code '%s' for kbid=%s", layout, variants, code, kbid)
            if not layout:
                log.debug("unknown keyboard layout for kbid: %s", kbid)
        except Exception, e:
            log.error("failed to detect keyboard layout: %s", e)
        return layout,variant,variants

    def get_keyboard_repeat(self):
        try:
            import win32con         #@UnresolvedImport
            import win32gui         #@UnresolvedImport
            _delay = win32gui.SystemParametersInfo(win32con.SPI_GETKEYBOARDDELAY)
            _speed = win32gui.SystemParametersInfo(win32con.SPI_GETKEYBOARDSPEED)
            #now we need to normalize those weird win32 values:
            #0=250, 3=1000:
            delay = (_delay+1) * 250
            #0=1000/30, 31=1000/2.5
            _speed = min(31, max(0, _speed))
            speed = int(1000/(2.5+27.5*_speed/31))
            log.debug("keyboard repeat speed(%s)=%s, delay(%s)=%s", _speed, speed, _delay, delay)
            return  delay,speed
        except Exception, e:
            log.error("failed to get keyboard rate: %s", e)
        return None


    def process_key_event(self, send_key_action_cb, wid, key_event):
        """ Caps_Lock and Num_Lock don't work properly: they get reported more than once,
            they are reported as not pressed when the key is down, etc
            So we just ignore those and rely on the list of "modifiers" passed
            with each keypress to let the server set them for us when needed.
        """
        if key_event.keyval==2**24-1 and key_event.keyname=="VoidSymbol":
            return
        #self.modifier_mappings = None       #{'control': [(37, 'Control_L'), (105, 'Control_R')], 'mod1':
        #self.modifier_keys = {}             #{"Control_L" : "control", ...}
        #self.modifier_keycodes = {}         #{"Control_R" : [105], ...}
        #self.modifier_keycodes = {"ISO_Level3_Shift": [108]}
        #we can only deal with 'Alt_R' and simulate AltGr (ISO_Level3_Shift)
        #if we have modifier_mappings
        if key_event.keyname=="Alt_R" and len(self.modifier_mappings)>0:
            keyname = "ISO_Level3_Shift"
            altgr_keycodes = self.modifier_keycodes.get(keyname, [])
            if len(altgr_keycodes)>0:
                self.emulate_altgr = key_event.pressed
                if key_event.pressed and self.last_key_event_sent:
                    #check for spurious control and undo it
                    last_wid, last_keyname, last_pressed = self.last_key_event_sent[:3]
                    if last_wid==wid and last_keyname=="Control_L" and last_pressed==True:
                        #undo it:
                        undo = self.last_key_event_sent[:]
                        undo[2] = False
                        send_key_action_cb(*undo)
                self.AltGr_modifiers(key_event.modifiers, not key_event.pressed)
        self.last_key_event_sent = key_event
        send_key_action_cb(wid, key_event)
