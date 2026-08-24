# This file is part of Xpra.
# Copyright (C) 2026 Yan Shoshitaishvili <yans@pwn.college>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from typing import Final

from xpra.keyboard.mask import MODIFIER_MAP, mask_to_names
from xpra.keyboard.keysyms import keysym_name
from xpra.keyboard.common import KeyEvent
from xpra.client.terminal.input import (
    KeyEvent as TerminalKeyEvent,
    MOD_SHIFT, MOD_ALT, MOD_CTRL, MOD_SUPER, MOD_HYPER, MOD_META, MOD_CAPS_LOCK, MOD_NUM_LOCK,
    KEY_TAB, KEY_ENTER, KEY_ESCAPE, KEY_BACKSPACE, KEY_PRESS, KEY_REPEAT,
)
from xpra.log import Logger

log = Logger("client", "keyboard")

# the kitty modifier bits, mapped to the canonical xpra modifier names.
# the names come straight from `DEFAULT_MODIFIER_MEANINGS` in `xpra.keyboard.mask`:
# `Alt_L` and `Meta_L` are both `mod1`, `Super_L` is `mod3`, `Hyper_L` is `mod4`,
# `Caps_Lock` is `lock` and `Num_Lock` is `mod2`:
KITTY_MODIFIERS: Final[dict[int, str]] = {
    MOD_SHIFT: "shift",
    MOD_ALT: "mod1",
    MOD_CTRL: "control",
    MOD_SUPER: "mod3",
    MOD_HYPER: "mod4",
    MOD_META: "mod1",
    MOD_CAPS_LOCK: "lock",
    MOD_NUM_LOCK: "mod2",
}


def _build_functional_keysyms() -> dict[int, str]:
    keysyms: dict[int, str] = {
        # the keys that keep their legacy encoding also keep their unicode code point:
        KEY_TAB: "Tab",
        KEY_ENTER: "Return",
        KEY_ESCAPE: "Escape",
        KEY_BACKSPACE: "BackSpace",
        # kitty's private use area numbers:
        57344: "Escape",
        57345: "Return",
        57346: "Tab",
        57347: "BackSpace",
        57348: "Insert",
        57349: "Delete",
        57350: "Left",
        57351: "Right",
        57352: "Up",
        57353: "Down",
        57354: "Page_Up",
        57355: "Page_Down",
        57356: "Home",
        57357: "End",
        57358: "Caps_Lock",
        57359: "Scroll_Lock",
        57360: "Num_Lock",
        57361: "Print",
        57362: "Pause",
        57363: "Menu",
        57409: "KP_Decimal",
        57410: "KP_Divide",
        57411: "KP_Multiply",
        57412: "KP_Subtract",
        57413: "KP_Add",
        57414: "KP_Enter",
        57415: "KP_Equal",
        57416: "KP_Separator",
        57417: "KP_Left",
        57418: "KP_Right",
        57419: "KP_Up",
        57420: "KP_Down",
        57421: "KP_Page_Up",
        57422: "KP_Page_Down",
        57423: "KP_Home",
        57424: "KP_End",
        57425: "KP_Insert",
        57426: "KP_Delete",
        57427: "KP_Begin",
        57428: "XF86AudioPlay",
        57429: "XF86AudioPause",
        57430: "XF86AudioPlay",
        57431: "XF86AudioRewind",
        57432: "XF86AudioStop",
        57433: "XF86AudioForward",
        57434: "XF86AudioRewind",
        57435: "XF86AudioNext",
        57436: "XF86AudioPrev",
        57437: "XF86AudioRecord",
        57438: "XF86AudioLowerVolume",
        57439: "XF86AudioRaiseVolume",
        57440: "XF86AudioMute",
        57441: "Shift_L",
        57442: "Control_L",
        57443: "Alt_L",
        57444: "Super_L",
        57445: "Hyper_L",
        57446: "Meta_L",
        57447: "Shift_R",
        57448: "Control_R",
        57449: "Alt_R",
        57450: "Super_R",
        57451: "Hyper_R",
        57452: "Meta_R",
        # `DEFAULT_MODIFIER_MEANINGS` only knows about `ISO_Level3_Shift` (`mod5`),
        # so kitty's ISO level 5 shift is reported as the level 3 one:
        57453: "ISO_Level3_Shift",
        57454: "ISO_Level3_Shift",
    }
    for i in range(1, 36):
        keysyms[57363 + i] = f"F{i}"
    for i in range(10):
        keysyms[57399 + i] = f"KP_{i}"
    return keysyms


FUNCTIONAL_KEYSYMS: Final[dict[int, str]] = _build_functional_keysyms()


# the kitty key codes of the (non-lock) modifier keys, with the kitty modifier
# bit each one drives - the lock keys are deliberately absent: their bit
# reflects the lock state, not whether the key is physically held:
MODIFIER_CODE_BITS: Final[dict[int, int]] = {
    57441: MOD_SHIFT, 57447: MOD_SHIFT,      # Shift_L, Shift_R
    57442: MOD_CTRL, 57448: MOD_CTRL,        # Control_L, Control_R
    57443: MOD_ALT, 57449: MOD_ALT,          # Alt_L, Alt_R
    57444: MOD_SUPER, 57450: MOD_SUPER,      # Super_L, Super_R
    57445: MOD_HYPER, 57451: MOD_HYPER,      # Hyper_L, Hyper_R
    57446: MOD_META, 57452: MOD_META,        # Meta_L, Meta_R
}


def keysym_name_for(code: int, text: str) -> str:
    """ the X11 keysym name for a key reported by the terminal """
    name = FUNCTIONAL_KEYSYMS.get(code, "")
    if name:
        return name
    if text:
        return keysym_name(text)
    if 0 < code <= 0x10FFFF:
        return keysym_name(chr(code))
    return ""


def key_text(ev: TerminalKeyEvent) -> str:
    """
    The text a key produced.
    The kitty keyboard protocol reports it directly under the "report associated text" flag,
    but never for a key release and never for a key which only produces control codes.
    When it is missing, the "shifted" alternate code point (reported under the
    "report alternate keys" flag) is what the key produces while `shift` is held:
    without it, the `A` we send to the server would be an `a`.
    """
    if ev.text:
        return ev.text
    shifted = ev.shifted
    if ev.mods & MOD_SHIFT and 0 < shifted <= 0x10FFFF and shifted not in FUNCTIONAL_KEYSYMS:
        char = chr(shifted)
        if char.isprintable():
            return char
    return ""


def modifier_names(kitty_mods: int) -> list[str]:
    """ the canonical xpra modifier names for a kitty modifier bitfield """
    mask = 0
    for bit, name in KITTY_MODIFIERS.items():
        if kitty_mods & bit:
            mask |= MODIFIER_MAP[name]
    return mask_to_names(mask, MODIFIER_MAP)


def keyval_for(code: int) -> int:
    """ the code point of a printable key, 0 for functional keys """
    if code <= 0 or code > 0x10FFFF or code in FUNCTIONAL_KEYSYMS:
        return 0
    return code if chr(code).isprintable() else 0


def make_key_event(ev: TerminalKeyEvent) -> KeyEvent:
    """ turn a terminal key event into the `KeyEvent` the keyboard subsystem expects """
    text = key_text(ev)
    key_event = KeyEvent()
    key_event.keyname = keysym_name_for(ev.code, text)
    key_event.pressed = ev.event_type in (KEY_PRESS, KEY_REPEAT)
    key_event.modifiers = modifier_names(ev.mods)
    key_event.string = text
    # the code point the key actually produced, so that the keyval matches the keysym name:
    key_event.keyval = keyval_for(ord(text) if len(text) == 1 else ev.code)
    key_event.keycode = 0
    key_event.group = 0
    log("make_key_event(%s)=%s", ev, key_event)
    return key_event
