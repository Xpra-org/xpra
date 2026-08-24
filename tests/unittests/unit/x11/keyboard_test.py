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


def main():
    # can only work with an X11 server
    if POSIX and not OSX:
        unittest.main()


if __name__ == '__main__':
    main()
