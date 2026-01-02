# This file is part of Xpra.
# Copyright (C) 2014 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from collections.abc import Sequence

from xpra.platform.win32.keyboard import fake_key, MOD_KEYS, VK_NAMES, KEYCODES
from xpra.server.keyboard_config_base import KeyboardConfigBase
from xpra.platform.win32.common import GetAsyncKeyState, VkKeyScanW
from xpra.log import Logger

log = Logger("keyboard")


class KeyboardConfig(KeyboardConfigBase):

    def __repr__(self):
        return "win32.KeyboardConfig"

    def do_get_keycode(self, client_keycode, keyname, pressed, modifiers, keyval, keystr, group) -> tuple[int, int]:
        keycode = KEYCODES.get(keyname, -1)
        if keycode == -1 and keystr and len(keystr) == 1:
            v = VkKeyScanW(keystr)
            vk_code = v & 0xff
            if vk_code > 0 and vk_code != 0xff:
                keycode = vk_code
        log("get_keycode%s=%s", (client_keycode, keyname, pressed, modifiers, keyval, keystr, group), keycode)
        return keycode, group

    def make_keymask_match(self, modifier_list, ignored_modifier_keycode=0, ignored_modifier_keynames=None) -> None:
        log("make_keymask_match%s", (modifier_list, ignored_modifier_keycode, ignored_modifier_keynames))
        log("keys pressed=%s", ",".join(str(VK_NAMES.get(i, i)) for i in range(256) if GetAsyncKeyState(i) > 0))
        current = set(self.get_current_mask())
        wanted = set(modifier_list or [])
        log("make_keymask_match: current mask=%s, wanted=%s, ignoring=%s/%s",
            current, wanted, ignored_modifier_keycode, ignored_modifier_keynames)
        if current == wanted:
            return

        def is_ignored(modifier) -> bool:
            if not modifier:
                return True
            if not ignored_modifier_keynames:
                return False
            for keyname in ignored_modifier_keynames:  # ie: ["Control_R"]
                keycode = KEYCODES.get(keyname, 0)  # ie: "Control_R" -> VK_RCONTROL
                if keycode > 0:
                    key_mod = MOD_KEYS.get(keycode)  # ie: "control"
                    if key_mod == modifier:
                        return True
            return False  # not found

        def change_mask(modifiers: set[str], press: bool, info: str) -> None:
            for modifier in modifiers:
                if is_ignored(modifier):
                    log("change_mask: ignoring %s", modifier)
                    continue
                # find the keycode:
                for k, v in MOD_KEYS.items():
                    if ignored_modifier_keycode and ignored_modifier_keycode == k:
                        log("change_mask: ignoring %s / %s", VK_NAMES.get(k, k), v)
                        continue
                    if v == modifier:
                        # figure out if this is the one that needs toggling:
                        is_pressed = GetAsyncKeyState(k)
                        log("make_keymask_match: %s pressed=%s", k, is_pressed)
                        if bool(is_pressed) != press:
                            log("make_keymask_match: using %s to %s %s", VK_NAMES.get(k, k), info, modifier)
                            fake_key(k, press)
                            break

        change_mask(current.difference(wanted), False, "remove")
        change_mask(wanted.difference(current), True, "add")

    def get_current_mask(self) -> Sequence[str]:
        mods = set()
        for vk, mod in MOD_KEYS.items():
            if GetAsyncKeyState(vk) != 0:
                mods.add(mod)
        return list(mods)
