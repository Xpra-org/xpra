#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2011 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import unittest

from unit.server_test_util import ServerTestUtil, log
from xpra.os_util import OSX, POSIX
from xpra.util.env import OSEnvContext


class TestX11Keyboard(ServerTestUtil):

    env_context = None
    gdk_display = None

    @classmethod
    def setUpClass(cls):
        ServerTestUtil.setUpClass()
        # the environment is restored in `tearDownClass`, so that the tests
        # running after this class are not left with a `DISPLAY`
        # pointing at the Xvfb we will have killed:
        cls.env_context = OSEnvContext(GDK_BACKEND="x11")
        cls.env_context.__enter__()
        display = cls.find_free_display()
        cls.xvfb = cls.start_Xvfb(display)
        os.environ["DISPLAY"] = display
        from xpra.x11.bindings.display_source import init_display_source  #@UnresolvedImport
        cls.display_ptr = init_display_source()
        from xpra.gtk.util import open_gdk_display
        cls.gdk_display = open_gdk_display(display)

    @classmethod
    def tearDownClass(cls):
        # both connections must be closed before the Xvfb is killed below,
        # or the stale connection will terminate this process
        # with an X11 IO error the next time a display is used:
        if cls.gdk_display:
            cls.gdk_display.close()
            cls.gdk_display = None
        from xpra.x11.bindings.display_source import close_display_source  #@UnresolvedImport
        close_display_source(cls.display_ptr)
        ServerTestUtil.tearDownClass()
        cls.xvfb.terminate()
        if cls.env_context:
            cls.env_context.__exit__()
            cls.env_context = None

    def test_unicode(self):
        from xpra.x11.bindings.keyboard import X11KeyboardBindings  #@UnresolvedImport
        keyboard_bindings = X11KeyboardBindings()
        for x in (
                "2030", "0005", "0010", "220F", "2039", "2211",
                "2248", "FB01", "F8FF", "203A", "FB02", "02C6",
                "02DA", "02DC", "2206", "2044", "25CA",
        ):
            # hex form:
            hk = keyboard_bindings.parse_keysym("0x" + x)
            # osx U+ form:
            uk = keyboard_bindings.parse_keysym("U+" + x)
            log("keysym(U+%s)=%#x, keysym(0x%s)=%#x", x, uk, x, hk)
            assert hk and uk
            assert uk == hk, "failed to get unicode keysym %s" % x

    def test_grok_modifier_map(self):
        from xpra.x11.xkbhelper import grok_modifier_map
        grok_modifier_map({"foo": 8})
        grok_modifier_map({})

    def test_parse(self):
        # the keyboard attributes are nested in a `keymap` dictionary in the hello packet,
        # but the `keyboard-config` packet contains them at the top level
        from xpra.util.objects import typedict
        from xpra.x11.server.keyboard_config import KeyboardConfig
        attributes = {
            "layout": "de",
            "keycodes": ((113, "q", 81, 0, 0), (64, "at", 81, 1, 0)),
            "mod_meanings": {"Alt_L": "mod1"},
            "mod_pointermissing": ("lock", ),
            "sync": False,
            "backend": "ibus",
            "backend_name": "xkb:de::ger",
        }
        # the `keyboard-config` packet is parsed with `parse`:
        config = KeyboardConfig()
        config.parse(typedict(dict(attributes, force=True)))
        for attr, value in attributes.items():
            parsed = getattr(config, "backend_engine" if attr == "backend_name" else attr)
            assert parsed == value, f"{attr!r} parsed as {parsed!r} from the `keyboard-config` packet"
        # the hello packet nests them, and is parsed with `parse_options` and `parse_layout`:
        config = KeyboardConfig()
        props = typedict({"keymap": dict(attributes)})
        config.parse_options(props)
        config.parse_layout(props)
        for attr in ("layout", "keycodes", "mod_meanings", "mod_pointermissing", "sync"):
            parsed = getattr(config, attr)
            assert parsed == attributes[attr], f"{attr!r} parsed as {parsed!r} from the hello packet"
        # clients older than v4.4 sent them at the top level with a `xkbmap_` prefix:
        config = KeyboardConfig()
        config.parse_options(typedict({f"xkbmap_{k}": v for k, v in attributes.items()}))
        for attr in ("keycodes", "mod_meanings", "mod_pointermissing"):
            parsed = getattr(config, attr)
            assert parsed == attributes[attr], f"{attr!r} parsed as {parsed!r} from a legacy hello packet"

    def test_altgr_keysyms(self):
        # see #4963: the keys only reachable via `AltGr` on a German keyboard
        # used to be resolved using the keymap the server had before the client connected
        from xpra.x11.xkbhelper import get_keycode_mappings, do_set_keymap
        from xpra.x11.server.keyboard_config import KeyboardConfig
        # the layout the server starts with, before any client has connected:
        do_set_keymap("us", "", "", {})
        config = KeyboardConfig()
        config.query_struct = {}
        config.layout = "de"
        # a subset of what a non-X11 client with a German layout sends,
        # as (keyval, keyname, keycode, group, level) - `AltGr` shows up as group 1:
        config.keycodes = (
            (113, "q", 81, 0, 0), (81, "Q", 81, 0, 1), (64, "at", 81, 1, 0),
            (50, "2", 50, 0, 0), (34, "quotedbl", 50, 0, 1),
            (60, "less", 226, 0, 0), (62, "greater", 226, 0, 1), (124, "bar", 226, 1, 0),
            (55, "7", 55, 0, 0), (47, "slash", 55, 0, 1), (123, "braceleft", 55, 1, 0),
            (0xffe1, "Shift_L", 16, 0, 0), (0xffe3, "Control_L", 17, 0, 0),
            (0xffe9, "Alt_L", 18, 0, 0), (0xffea, "Alt_R", 165, 0, 0),
        )
        config.set_keymap()
        mappings = get_keycode_mappings()
        if mappings.get(24, ())[2:3] != ["at"]:
            raise unittest.SkipTest("no German keymap available")

        def keysym_produced(keysym: str, client_keycode: int, group: int) -> str:
            modifiers = []
            config.pressed_translation = {}
            keycode, group = config.get_keycode(client_keycode, keysym, True, modifiers, 0, "", group)
            keysyms = mappings.get(keycode, ())
            level = int("shift" in modifiers) + 4 * group
            for mod in modifiers:
                if set(config.keynames_for_mod.get(mod, ())) & {"ISO_Level3_Shift", "Mode_switch"}:
                    level += 2
            log("%r=%s, modifiers=%s, keysyms=%s, level=%i", keysym, keycode, modifiers, keysyms, level)
            return keysyms[level] if len(keysyms) > level else ""

        for keysym, client_keycode, group in (
            # `AltGr` combinations:
            ("at", 81, 1), ("bar", 226, 1), ("braceleft", 55, 1),
            # and the plain and shifted keys:
            ("q", 81, 0), ("Q", 81, 0), ("2", 50, 0), ("quotedbl", 50, 0), ("less", 226, 0),
        ):
            produced = keysym_produced(keysym, client_keycode, group)
            assert produced == keysym, f"expected {keysym!r} but the server would produce {produced!r}"

    def test_keyval_group(self):
        # the last resort keyval lookup should honour the group the client sent,
        # and set the modifiers needed to reach the level the keysym is at
        from xpra.x11.xkbhelper import do_set_keymap, get_keyval_mappings
        from xpra.x11.server.keyboard_config import KeyboardConfig
        # two groups: `AltGr` and friends aside, group 1 is reached by switching layout
        do_set_keymap("us,de", "", "", {})
        keyval_mappings = get_keyval_mappings()
        # we need keysyms which live on a different keycode in each group,
        # otherwise we cannot tell which group was used:
        candidates = tuple(
            (keyval, groups) for keyval, groups in keyval_mappings.items()
            if len(groups) > 1 and len(set(entries[0][0] for entries in groups.values())) > 1
        )
        if not candidates:
            raise unittest.SkipTest("no keysym found on more than one group")
        config = KeyboardConfig()
        config.keyval_mappings = keyval_mappings
        # so that `mod5` can be toggled to reach the `AltGr` levels:
        config.compute_modifiers()
        # a keyname the server knows nothing about, so that every keyname lookup fails
        # and we always end up in the keyval fallback:
        keyname = "xpra_unmatched_keyname"
        levels_used = set()

        def press(keyval: int, group: int) -> tuple[int, int, int]:
            # returns the (keycode, group, level) the server would actually use
            modifiers: list[str] = []
            config.pressed_translation = {}
            keycode, rgroup = config.get_keycode(0, keyname, True, modifiers, keyval, "", group)
            mode = any(set(config.keynames_for_mod.get(mod, ())) & {"ISO_Level3_Shift", "Mode_switch"}
                       for mod in modifiers)
            level = int("shift" in modifiers) + 2 * int(mode)
            log("keyval %#x group %i: keycode=%i, group=%i, modifiers=%s, level=%i",
                keyval, group, keycode, rgroup, modifiers, level)
            levels_used.add(level)
            return keycode, rgroup, level

        for keyval, groups in candidates:
            for group, entries in groups.items():
                keycode, rgroup, level = press(keyval, group)
                assert rgroup == group, \
                    f"group {group} was not preserved for keyval {keyval:#x}, got {rgroup}"
                assert (keycode, level) in entries, \
                    f"keyval {keyval:#x} in group {group}: keycode {keycode} at level {level} " \
                    f"does not produce it, only {entries} do"
        # clients can send a group which does not exist on the server:
        # we should then fall back to the lowest group which has this keysym,
        # deterministically - and not to whichever one happens to come last
        missing_group = max(max(groups) for groups in keyval_mappings.values()) + 1
        for keyval, groups in candidates:
            lowest = min(groups)
            keycode, rgroup, level = press(keyval, missing_group)
            assert rgroup == lowest, \
                f"expected group {lowest} for keyval {keyval:#x} not in group {missing_group}, got {rgroup}"
            assert (keycode, level) in groups[lowest], \
                f"keyval {keyval:#x} in group {lowest}: keycode {keycode} at level {level} " \
                f"does not produce it, only {groups[lowest]} do"
        # the shifted and `AltGr` levels must have been exercised above,
        # or we would not be testing much:
        assert levels_used.issuperset({0, 1, 2}), f"only levels {levels_used} were tested"

    def test_keysym_aliases(self):
        # keysyms have more than one name and the layers do not agree on which one to use:
        # GDK says `Page_Up` and `AudioMute` where X11 says `Prior` and `XF86AudioMute`
        from gi.repository import Gdk  # @UnresolvedImport pylint: disable=import-outside-toplevel
        from xpra.x11.xkbhelper import (
            do_set_keymap, get_keycode_mappings, set_keycode_translation, canonical_keysym,
        )
        from xpra.x11.bindings.keyboard import X11KeyboardBindings
        from xpra.x11.server.keyboard_config import KeyboardConfig
        do_set_keymap("us", "", "", {})
        for keyname, expected in (
            ("Page_Up", "Prior"), ("Page_Down", "Next"), ("KP_Page_Up", "KP_Prior"),
            ("AudioMute", "XF86AudioMute"), ("0x1008ff12", "XF86AudioMute"), ("U+0041", "A"),
            # already the name the X11 server uses, or not a keysym name at all:
            ("Prior", "Prior"), ("a", "a"), ("", ""), ("\u2192", "\u2192"), ("xpra_unknown_keyname", "xpra_unknown_keyname"),
        ):
            canonical = canonical_keysym(keyname)
            assert canonical == expected, f"canonical_keysym({keyname!r})={canonical!r}, expected {expected!r}"

        # a GTK client which has no `x11_keycodes` to send (ie: running on wayland)
        # uses the GDK name for every keysym, both in its keymap and in its key events:
        X11Keyboard = X11KeyboardBindings()
        mappings = get_keycode_mappings()
        keycode_for_keyname: dict[str, int] = {}
        for keycode, keynames in mappings.items():
            for keyname in keynames:
                if keyname:
                    keycode_for_keyname.setdefault(keyname, keycode)
        client_keynames = {}
        for keyname in keycode_for_keyname:
            keyval = X11Keyboard.parse_keysym(keyname)
            client_keynames[keyname] = Gdk.keyval_name(keyval) or keyname
        aliased = tuple(keyname for keyname, cname in client_keynames.items() if keyname != cname)
        log("GDK names %i of the %i server keysyms differently: %s", len(aliased), len(client_keynames), aliased)
        assert aliased, "GDK agrees with X11 on the name of every keysym?"

        # none of its keymap entries should be dropped:
        client_keycodes = tuple(
            (X11Keyboard.parse_keysym(keyname), cname, keycode_for_keyname[keyname], 0, 0)
            for keyname, cname in client_keynames.items()
        )
        trans = set_keycode_translation({}, client_keycodes)
        missing = tuple(cname for cname in client_keynames.values() if not trans.get(cname))
        assert not missing, f"the client keymap entries for {missing} were dropped"

        # and its key events should resolve to the same keycode as the X11 name,
        # with no keyval for the last resort lookup to use:
        config = KeyboardConfig()
        config.update_keycode_mappings()

        def keycode_for(keyname: str) -> int:
            config.pressed_translation = {}
            return config.get_keycode(0, keyname, True, [], 0, "", 0)[0]

        for keyname, cname in client_keynames.items():
            keycode = keycode_for(cname)
            expected = keycode_for(keyname)
            assert keycode == expected, \
                f"the client name {cname!r} resolved to keycode {keycode}, " \
                f"but the server name {keyname!r} resolves to {expected}"

    def test_native_keycode_keysym_mismatch(self):
        # A native client keymap can become stale, or omit the key event's keysym.
        # Do not send its numeric keycode if it produces a different server keysym.
        from xpra.x11.xkbhelper import do_set_keymap, get_keycode_mappings
        from xpra.x11.server.keyboard_config import KeyboardConfig
        do_set_keymap("us", "", "", {})
        mappings = get_keycode_mappings()
        keyname = "Prior"
        server_keycode = next((keycode for keycode, keysyms in mappings.items() if keyname in keysyms), 0)
        if not server_keycode:
            raise unittest.SkipTest(f"no {keyname!r} keycode in the server keymap")
        client_keycode = next(
            keycode for keycode, keysyms in mappings.items()
            if keycode != server_keycode and keyname not in keysyms
        )
        config = KeyboardConfig()
        config.x11_keycodes = {client_keycode: (keyname, )}
        config.keycode_mappings = mappings
        # This is the usual non-keycode-specific mapping, retained even if
        # the matching (client_keycode, keyname) entry is missing.
        config.keycode_translation = {keyname: server_keycode}
        keycode, group = config.get_keycode(client_keycode, keyname, True, [], 0, "", 0)
        assert keycode == server_keycode
        assert group == 0

    def test_keys_changed(self):
        # the lookup tables are derived from the server's keymap,
        # so they have to be re-derived when something inside the session changes it
        # (ie: `setxkbmap`, `xmodmap`, or an ibus engine switching layout)
        from xpra.x11.xkbhelper import get_keycode_mappings, do_set_keymap
        from xpra.x11.server.keyboard_config import KeyboardConfig
        do_set_keymap("us", "", "", {})
        config = KeyboardConfig()
        config.query_struct = {}
        config.layout = "us"
        # a non-X11 client (ie: HTML5) sends `keycodes` but no `x11_keycodes`,
        # so its keys are resolved against the server's keymap:
        config.keycodes = (
            (113, "q", 81, 0, 0), (81, "Q", 81, 0, 1),
            (0xffe1, "Shift_L", 16, 0, 0), (0xffe3, "Control_L", 17, 0, 0),
        )
        config.set_keymap()

        def get_keycode(keysym: str) -> int:
            config.pressed_translation = {}
            # `keyval` is left at zero to avoid the keyval fallback:
            return config.get_keycode(0, keysym, True, [], 0, "", 0)[0]

        assert get_keycode("adiaeresis") < 0, "'adiaeresis' should not be reachable with a 'us' layout"
        # something else changes the keymap from within the session:
        do_set_keymap("de", "", "", {})
        mappings = get_keycode_mappings()
        if not any("adiaeresis" in keysyms for keysyms in mappings.values()):
            raise unittest.SkipTest("no German keymap available")
        # until it is told about it, the config still describes the keymap we started with:
        assert config.keycode_mappings != mappings, "the keycode mappings should still be stale"
        assert get_keycode("adiaeresis") < 0, "'adiaeresis' should not be resolved from a stale keymap"
        config.keys_changed()
        assert config.keycode_mappings == mappings, "the keycode mappings were not refreshed"
        keycode = get_keycode("adiaeresis")
        assert "adiaeresis" in mappings.get(keycode, ()), \
            f"'adiaeresis' was resolved to keycode {keycode}: {mappings.get(keycode)}"

    def test_keys_changed_after_set_keymap(self):
        # setting a keymap ourselves also fires the `keys-changed` signal:
        # the x11 keyboard subsystem suppresses it whilst the new keymap is applied,
        # then calls `_keys_changed()` itself when the suppression timer expires.
        # So `keys_changed()` always runs just after `set_keymap()`,
        # and it must not undo anything `set_keymap()` had just set up.
        from copy import deepcopy
        from xpra.x11.xkbhelper import do_set_keymap
        from xpra.x11.server.keyboard_config import KeyboardConfig
        # (`modifier_map` is left out: `set_keymap()` never computes it,
        # `compute_modifier_map()` is what refreshes it from the parsed `mod_meanings`)
        attrs = (
            "keycode_translation", "keycode_mappings", "keyval_mappings", "keynames_for_mod",
            "keycodes_for_modifier_keynames", "modifier_client_keycodes", "mod_nuisance",
        )
        keycodes = (
            (113, "q", 81, 0, 0), (81, "Q", 81, 0, 1),
            (50, "2", 50, 0, 0), (34, "quotedbl", 50, 0, 1),
            (0xffe1, "Shift_L", 16, 0, 0), (0xffe3, "Control_L", 17, 0, 0),
            (0xffe9, "Alt_L", 18, 0, 0), (0xffea, "Alt_R", 165, 0, 0),
        )
        # with and without a native client keymap, since they build the translation differently:
        for x11_keycodes in ({}, {81: ("q", "Q"), 50: ("2", "quotedbl"), 16: ("Shift_L", )}):
            do_set_keymap("us", "", "", {})
            config = KeyboardConfig()
            config.query_struct = {}
            config.layout = "us"
            config.x11_keycodes = x11_keycodes
            config.keycodes = keycodes
            config.set_keymap()
            expected = {attr: deepcopy(getattr(config, attr)) for attr in attrs}
            config.keys_changed()
            for attr, value in expected.items():
                assert getattr(config, attr) == value, \
                    f"keys_changed() modified {attr!r} set up by set_keymap(), x11_keycodes={bool(x11_keycodes)}"
            # and it must settle: calling it again changes nothing at all
            expected = {attr: deepcopy(getattr(config, attr)) for attr in attrs + ("modifier_map", )}
            config.keys_changed()
            for attr, value in expected.items():
                assert getattr(config, attr) == value, f"keys_changed() is not idempotent for {attr!r}"


def main():
    # can only work with an X11 server
    if POSIX and not OSX:
        unittest.main()


if __name__ == '__main__':
    main()
