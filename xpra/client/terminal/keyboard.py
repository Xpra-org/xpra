# This file is part of Xpra.
# Copyright (C) 2026 Yan Shoshitaishvili <yans@pwn.college>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from typing import Any, Final
from collections.abc import Sequence

from xpra.keyboard.mask import DEFAULT_MODIFIER_MEANINGS
from xpra.platform.keyboard_base import KeyboardBase
from xpra.client.gui.keyboard_helper import KeyboardHelper
from xpra.client.terminal.input import SGR_MODIFIERS
from xpra.client.terminal.keys import FUNCTIONAL_KEYSYMS, KITTY_MODIFIERS

# the terminal tells us which key was pressed, not which keycode was used to press it,
# so the server maps the key names we send: the layout below is just what it should load
# to be able to find them:
KEYBOARD_MODEL: Final[str] = "pc105"
KEYBOARD_LAYOUT: Final[str] = "us"
# the modifier meanings, limited to the key names the terminal can actually produce
# (see `xpra.client.terminal.keys`), so that the server does not expect
# modifier keys we will never send:
MOD_MEANINGS: Final[dict[str, str]] = {
    keyname: modifier for keyname, modifier in DEFAULT_MODIFIER_MEANINGS.items()
    if keyname in frozenset(FUNCTIONAL_KEYSYMS.values())
}
# the modifiers a mouse report can carry: SGR reports only have three modifier bits
# (see `SGR_MODIFIERS` in `xpra.client.terminal.input`), whereas key events carry
# the whole kitty modifier bitfield:
POINTER_MODIFIERS: Final[frozenset[str]] = frozenset(
    KITTY_MODIFIERS[bit] for bit in SGR_MODIFIERS.values() if bit in KITTY_MODIFIERS
)
# every other modifier we can send is therefore missing from our pointer events:
# the lock modifiers, `Super`, `Hyper` and the level 3 shift.
# the server must leave those alone when it processes a pointer, button or focus packet,
# or it would press keys we never pressed to clear modifiers we simply cannot report
# (see `make_keymask_match` in `xpra.x11.server.keyboard_config`):
MOD_POINTERMISSING: Final[Sequence[str]] = tuple(sorted(set(MOD_MEANINGS.values()) - POINTER_MODIFIERS))


class TerminalKeyboard(KeyboardBase):
    """
    The `keyboard` implementation for terminals.

    There is no local keymap to query: the terminal reports key names
    (via the kitty keyboard protocol, see `xpra.client.terminal.keys`)
    and the modifiers that were held down with them.
    """

    def __repr__(self):
        return "TerminalKeyboard"

    def get_keymap_modifiers(self) -> tuple[dict, list[str], list[str]]:
        # (mod_meanings, mod_managed, mod_pointermissing):
        # the terminal reports the caps lock and num lock state with every key event,
        # so the server has no modifier to manage.
        # mouse events are another matter: they only carry `shift`, `control` and `mod1`.
        return dict(MOD_MEANINGS), [], list(MOD_POINTERMISSING)

    def get_keymap_spec(self) -> dict[str, Any]:
        # no xkb rules to query: we don't have a local keyboard mapping
        return {}

    def get_x11_keymap(self) -> dict[int, list[str]]:
        return {}

    def get_layout_spec(self) -> tuple[str, str, Sequence[str], str, Sequence[str], str]:
        # (model, layout, layouts, variant, variants, options)
        return KEYBOARD_MODEL, KEYBOARD_LAYOUT, [KEYBOARD_LAYOUT], "", [], ""

    def get_keyboard_repeat(self) -> tuple[int, int] | None:
        # the terminal repeats keys for us: each repeat is delivered as an event,
        # which the client turns into a new key press.
        # returning `None` also keeps `keyboard_sync` disabled, which is what we want:
        # we cannot know when a key is released if the terminal does not tell us.
        return None


class TerminalKeyboardHelper(KeyboardHelper):
    """
    `KeyboardHelper` using `TerminalKeyboard` instead of the platform keyboard.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # our keymap never changes, query it once so the hello capabilities have it:
        self.update()

    def make_keyboard(self) -> TerminalKeyboard:
        # the platform keyboard queries the local X11 keymap and the GNOME input
        # sources over dbus (and can end up importing Gdk):
        # none of that applies to a terminal client
        return TerminalKeyboard()

    def __repr__(self):
        return "TerminalKeyboardHelper"
