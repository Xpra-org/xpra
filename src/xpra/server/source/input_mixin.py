# -*- coding: utf-8 -*-
# This file is part of Xpra.
# Copyright (C) 2010-2020 Antoine Martin <antoine@xpra.org>
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.server.source.stub_source_mixin import StubSourceMixin
from xpra.keyboard.mask import DEFAULT_MODIFIER_MEANINGS
from xpra.util import typedict
from xpra.log import Logger

log = Logger("keyboard")


"""
Manage input devices (keyboard, mouse, etc)
"""
class InputMixin(StubSourceMixin):

    @classmethod
    def is_needed(cls, caps : typedict) -> bool:
        #the 'keyboard' and 'mouse' capability were only added in v4,
        #so we have to enable the mixin by default:
        return caps.boolget("keyboard", True) or caps.boolget("mouse", True)

    def init_state(self):
        self.pointer_relative = False
        self.keyboard_config = None
        self.double_click_time  = -1
        self.double_click_distance = -1, -1
        # mouse echo:
        self.mouse_show = False
        self.mouse_last_position = None
        self.mouse_last_relative_position = None

    def cleanup(self):
        self.keyboard_config = None

    def parse_client_caps(self, c : typedict):
        self.pointer_relative = c.boolget("pointer.relative")
        self.double_click_time = c.intget("double_click.time")
        self.double_click_distance = c.intpair("double_click.distance")
        self.mouse_show = c.boolget("mouse.show")
        self.mouse_last_position = c.intpair("mouse.initial-position")


    def get_info(self) -> dict:
        dc_info = {}
        dct = self.double_click_time
        if dct:
            dc_info["time"] = dct
        dcd = self.double_click_distance
        if dcd:
            dc_info["distance"] = dcd
        info = {}
        if dc_info:
            info["double-click"] = dc_info
        kc = self.keyboard_config
        if kc:
            info["keyboard"] = kc.get_info()
        return info

    def get_caps(self) -> dict:
        #expose the "modifier_client_keycodes" defined in the X11 server keyboard config object,
        #so clients can figure out which modifiers map to which keys:
        kc = self.keyboard_config
        if kc:
            mck = getattr(kc, "modifier_client_keycodes", None)
            if mck:
                return {"modifier_keycodes" : mck}
        return {}


    def set_layout(self, layout, variant, options):
        return self.keyboard_config.set_layout(layout, variant, options)

    def keys_changed(self):
        kc = self.keyboard_config
        if kc:
            kc.compute_modifier_map()
            kc.compute_modifier_keynames()
        log("keys_changed() updated keyboard config=%s", self.keyboard_config)

    def make_keymask_match(self, modifier_list, ignored_modifier_keycode=None, ignored_modifier_keynames=None):
        kc = self.keyboard_config
        if kc and kc.enabled:
            kc.make_keymask_match(modifier_list, ignored_modifier_keycode, ignored_modifier_keynames)

    def set_default_keymap(self):
        log("set_default_keymap() keyboard_config=%s", self.keyboard_config)
        kc = self.keyboard_config
        if kc:
            kc.set_default_keymap()
        return kc


    def is_modifier(self, keyname, keycode) -> bool:
        if keyname in DEFAULT_MODIFIER_MEANINGS.keys():
            return True
        #keyboard config should always exist if we are here?
        kc = self.keyboard_config
        if kc:
            return kc.is_modifier(keycode)
        return False


    def set_keymap(self, current_keyboard_config, keys_pressed, force=False, translate_only=False):
        kc = self.keyboard_config
        log("set_keymap%s keyboard_config=%s", (current_keyboard_config, keys_pressed, force, translate_only), kc)
        if kc and kc.enabled:
            current_id = None
            if current_keyboard_config and current_keyboard_config.enabled:
                current_id = current_keyboard_config.get_hash()
            keymap_id = kc.get_hash()
            log("current keyboard id=%s, new keyboard id=%s", current_id, keymap_id)
            if force or current_id is None or keymap_id!=current_id:
                kc.keys_pressed = keys_pressed
                kc.set_keymap(translate_only)
                kc.owner = self.uuid
            else:
                log.info("keyboard mapping already configured (skipped)")
                self.keyboard_config = current_keyboard_config


    def get_keycode(self, client_keycode, keyname, pressed, modifiers, keystr, group) -> int:
        kc = self.keyboard_config
        if kc is None:
            log.info("ignoring client key %s / %s since keyboard is not configured", client_keycode, keyname)
            return -1
        return kc.get_keycode(client_keycode, keyname, pressed, modifiers, keystr, group)


    def update_mouse(self, wid, x, y, rx, ry):
        log("update_mouse(%s, %i, %i, %i, %i) current=%s, client=%i, show=%s",
            wid, x, y, rx, ry, self.mouse_last_position, self.counter, self.mouse_show)
        if not self.mouse_show:
            return
        if self.mouse_last_position!=(x, y, rx, ry):
            self.mouse_last_position = (x, y, rx, ry)
            self.send_async("pointer-position", wid, x, y, rx, ry)
