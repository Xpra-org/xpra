# coding=utf8
# This file is part of Xpra.
# Copyright (C) 2010-2016 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.log import Logger
log = Logger("keyboard")


class KeyboardConfigBase(object):
    """ Base class representing the keyboard configuration for a server.
    """

    def __init__(self):
        self.enabled = True
        self.is_native_keymap = True
        self.owner = None

    def __repr__(self):
        return "KeyboardConfigBase"

    def get_info(self):
        return {
                "enabled"   : self.enabled,
                "native"    : self.is_native_keymap,
                "owner"     : self.owner or "",
                }

    def parse_options(self, props):
        pass

    def get_hash(self):
        return ""

    def set_layout(self, layout, variant):
        pass

    def set_keymap(self, translate_only=False):
        pass

    def set_default_keymap(self):
        pass

    def make_keymask_match(self, modifier_list, ignored_modifier_keycode=None, ignored_modifier_keynames=None):
        pass

    def get_keycode(self, _client_keycode, _keyname, _modifiers):
        log("%s does not implement get_keycode!", type(self))
        return -1

    def is_modifier(self, _keycode):
        #should be overriden in subclass
        return False
