# This file is part of Xpra.
# Copyright (C) 2014 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from collections.abc import Sequence

from xpra.platform.win32.keyboard import (
    fake_key, MOD_KEYS, VK_NAMES, KEYCODES,
    UNICODE_KEY, SHIFT_STATE_SHIFT, SHIFT_STATE_ALTGR,
    find_character_key, get_foreground_layout,
)
from xpra.server.keyboard_config_base import KeyboardConfigBase
from xpra.platform.win32.common import GetAsyncKeyState, VkKeyScanW
from xpra.util.env import envbool
from xpra.log import Logger

log = Logger("keyboard")

# Type the character of the keys that have one, using the layout of the window receiving the key events,
# or the character itself if this layout cannot type it.
# When disabled, keys are mapped by name, and the MS Windows layout decides the character.
KEYS_BY_CHARACTER = envbool("XPRA_WIN32_KEYS_BY_CHARACTER", True)
# these modifiers make a shortcut rather than type a character:
SHORTCUT_MODIFIERS = ("control", "mod1", "mod4")


def is_text(keyname: str, keystr: str, modifiers: Sequence[str]) -> bool:
    if len(keystr) != 1 or not keystr.isprintable() or keystr == " ":
        return False
    # the keypad keys have their own virtual keys, ie: `KP_1` is not `1`:
    if keyname.startswith("KP_"):
        return False
    return not any(modifier in modifiers for modifier in SHORTCUT_MODIFIERS)


def get_character_keycode(char: str, modifiers: list[str]) -> int:
    """
    Find the key that types `char` with the layout of the window receiving the key events,
    and update `modifiers` with the `Shift` and `AltGr` state that this key needs.
    """
    vk, shift_state = find_character_key(char, "lock" in modifiers, get_foreground_layout())
    if not vk:
        return UNICODE_KEY | ord(char)
    if "shift" in modifiers:
        modifiers.remove("shift")
    if shift_state & SHIFT_STATE_SHIFT:
        modifiers.append("shift")
    if shift_state & SHIFT_STATE_ALTGR:
        # `AltGr` is `Control+Alt` for MS Windows:
        modifiers += ["control", "mod1"]
    return vk


class KeyboardConfig(KeyboardConfigBase):

    def __repr__(self):
        return "win32.KeyboardConfig"

    def do_get_keycode(self, client_keycode, keyname, pressed, modifiers, keyval, keystr, group) -> tuple[int, int]:
        if KEYS_BY_CHARACTER and is_text(keyname, keystr, modifiers):
            keycode = get_character_keycode(keystr, modifiers)
        else:
            keycode = KEYCODES.get(keyname, -1)
            if keycode == -1 and keystr and len(keystr) == 1:
                v = VkKeyScanW(keystr)
                vk_code = v & 0xff
                # a character that needs `Control` but not `AltGr` is a control character,
                # which the key does not produce on its own,
                # ie: the NUL string of `KP_Page_Up` is `Control+Shift+2`:
                control_char = ((v >> 8) & 0x6) == 0x2
                if vk_code > 0 and vk_code != 0xff and not control_char:
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
