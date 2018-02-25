# -*- coding: utf-8 -*-
# This file is part of Xpra.
# Copyright (C) 2010-2018 Antoine Martin <antoine@devloop.org.uk>
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.log import Logger
log = Logger("keyboard")

from xpra.server.source.stub_source_mixin import StubSourceMixin


"""
Manage input devices (keyboard, mouse, etc)
"""
class InputMixin(StubSourceMixin):

    def init_state(self):
        self.keyboard_config = None
        self.double_click_time  = -1
        self.double_click_distance = -1, -1

    def cleanup(self):
        self.keyboard_config = None

    def parse_client_caps(self, c):
        self.double_click_time = c.intget("double_click.time")
        self.double_click_distance = c.intpair("double_click.distance")


    def get_info(self):
        info = {
            "time"      : self.double_click_time,
            "distance"  : self.double_click_distance,
            }
        return {"double-click" : info}

    def get_caps(self):
        #expose the "modifier_client_keycodes" defined in the X11 server keyboard config object,
        #so clients can figure out which modifiers map to which keys:
        if self.keyboard_config:
            mck = getattr(self.keyboard_config, "modifier_client_keycodes", None)
            if mck:
                return {"modifier_keycodes" : mck}
        return {}
        

    def set_layout(self, layout, variant, options):
        return self.keyboard_config.set_layout(layout, variant, options)

    def keys_changed(self):
        if self.keyboard_config:
            self.keyboard_config.compute_modifier_map()
            self.keyboard_config.compute_modifier_keynames()
        log("keys_changed() updated keyboard config=%s", self.keyboard_config)

    def make_keymask_match(self, modifier_list, ignored_modifier_keycode=None, ignored_modifier_keynames=None):
        if self.keyboard_config and self.keyboard_config.enabled:
            self.keyboard_config.make_keymask_match(modifier_list, ignored_modifier_keycode, ignored_modifier_keynames)

    def set_default_keymap(self):
        log("set_default_keymap() keyboard_config=%s", self.keyboard_config)
        if self.keyboard_config:
            self.keyboard_config.set_default_keymap()
        return self.keyboard_config


    def set_keymap(self, current_keyboard_config, keys_pressed, force=False, translate_only=False):
        log("set_keymap%s", (current_keyboard_config, keys_pressed, force, translate_only))
        if self.keyboard_config and self.keyboard_config.enabled:
            current_id = None
            if current_keyboard_config and current_keyboard_config.enabled:
                current_id = current_keyboard_config.get_hash()
            keymap_id = self.keyboard_config.get_hash()
            log("current keyboard id=%s, new keyboard id=%s", current_id, keymap_id)
            if force or current_id is None or keymap_id!=current_id:
                self.keyboard_config.keys_pressed = keys_pressed
                self.keyboard_config.set_keymap(translate_only)
                self.keyboard_config.owner = self.uuid
                current_keyboard_config = self.keyboard_config
            else:
                log.info("keyboard mapping already configured (skipped)")
                self.keyboard_config = current_keyboard_config
        return current_keyboard_config


    def get_keycode(self, client_keycode, keyname, modifiers):
        if self.keyboard_config is None:
            log.info("ignoring client key %s / %s since keyboard is not configured", client_keycode, keyname)
            return -1
        return self.keyboard_config.get_keycode(client_keycode, keyname, modifiers)


    def update_mouse(self, wid, x, y, rx, ry):
        log("update_mouse(%s, %i, %i, %i, %i) current=%s, client=%i, show=%s", wid, x, y, rx, ry, self.mouse_last_position, self.counter, self.mouse_show)
        if not self.mouse_show:
            return
        if self.mouse_last_position!=(x, y, rx, ry):
            self.mouse_last_position = (x, y, rx, ry)
            self.send_async("pointer-position", wid, x, y, rx, ry)
