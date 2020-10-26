# -*- coding: utf-8 -*-
# This file is part of Xpra.
# Copyright (C) 2010-2018 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.


class KeyboardConfigBase(object):
    """ Base class representing the keyboard configuration for a server.
    """

    def __init__(self):
        self.enabled = True
        self.owner = None
        self.sync = True
        self.pressed_translation = {}

    def __repr__(self):
        return "KeyboardConfigBase"

    def get_info(self):
        return {
                "enabled"   : self.enabled,
                "owner"     : self.owner or "",
                "sync"      : self.sync,
                }

    def parse_options(self, props):
        self.sync = props.boolget("keyboard_sync", True)

    def get_hash(self):
        return b""

    def set_layout(self, layout, variant, options):
        pass

    def set_keymap(self, translate_only=False):
        pass

    def set_default_keymap(self):
        pass

    def make_keymask_match(self, modifier_list, ignored_modifier_keycode=None, ignored_modifier_keynames=None):
        pass

    def get_keycode(self, client_keycode, keyname, pressed, modifiers, keystr, group):
        if not keyname and client_keycode<0:
            return -1, group
        if not pressed:
            r = self.pressed_translation.get(client_keycode)
            if r:
                #del self.pressed_translation[client_keycode]
                return r
        keycode, group = self.do_get_keycode(client_keycode, keyname, pressed, modifiers, keystr, group)
        if pressed not in (None, -1):
            #keep track of it so we can unpress the same key:
            self.pressed_translation[client_keycode] = keycode, group
        return keycode, group

    def do_get_keycode(self, _client_keycode, _keyname, _pressed, _modifiers, _keystr, _group):
        from xpra.log import Logger
        log = Logger("keyboard")
        log.warn("Warning: %s does not implement get_keycode!", type(self))
        return -1

    def is_modifier(self, _keycode):
        #should be overriden in subclass
        return False
