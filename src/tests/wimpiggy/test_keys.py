# This file is part of Xpra.
# Copyright (C) 2008, 2009 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

#@PydevCodeAnalysisIgnore

from wimpiggy.test import *
import subprocess
import wimpiggy.keys
from wimpiggy.lowlevel import xtest_fake_key

# FIXME: test the actual keybinding stuff!  But this require XTest support.

class TestKeys(TestWithSession):
    def xmodmap(self, code):
        xmodmap = subprocess.Popen(["xmodmap",
                                    "-display", self.display_name,
                                    "-"],
                                   stdin=subprocess.PIPE)
        xmodmap.communicate(code)
        subprocess.call(["xmodmap", "-display", self.display_name, "-pm"])
        self.display.flush()

    def clear_xmodmap(self):
        # No assigned modifiers, but all modifier keys *have* keycodes for
        # later.
        self.xmodmap("""clear Lock
                        clear Shift
                        clear Control
                        clear Mod1
                        clear Mod2
                        clear Mod3
                        clear Mod4
                        clear Mod5
                        keycode any = Num_Lock
                        keycode any = Scroll_Lock
                        keycode any = Hyper_L
                        keycode any = Hyper_R
                        keycode any = Super_L
                        keycode any = Super_R
                        keycode any = Alt_L
                        keycode any = Alt_R
                        keycode any = Meta_L
                        keycode any = Meta_R
                        """)

    def test_grok_modifier_map(self):
        self.clear_xmodmap()
        mm = wimpiggy.keys.grok_modifier_map(self.display)
        print(mm)
        assert mm == {"shift": 1, "lock": 2, "control": 4,
                      "mod1": 8, "mod2": 16, "mod3": 32, "mod4": 64,
                      "mod5": 128,
                      "scroll": 0, "num": 0, "meta": 0, "super": 0,
                      "hyper": 0, "alt": 0, "nuisance": 2}

        self.xmodmap("""add Mod1 = Num_Lock Hyper_L
                        add Mod2 = Hyper_R Meta_L Alt_L
                        add Mod3 = Super_R
                        add Mod4 = Alt_R Meta_R Super_L
                        add Mod5 = Scroll_Lock Super_R
                        """)
        mm = wimpiggy.keys.grok_modifier_map(self.display)
        print(mm)
        assert mm["scroll"] == 128
        assert mm["num"] == 8
        assert mm["meta"] == 16 | 64
        assert mm["super"] == 32 | 64 | 128
        assert mm["hyper"] == 8 | 16
        assert mm["alt"] == 16 | 64
        assert mm["nuisance"] == 2 | 8 | 128

    def test_parse_unparse_keys(self):
        self.clear_xmodmap()
        self.xmodmap("""add Mod1 = Meta_L Meta_R Alt_L
                        !add Mod2 =
                        add Mod3 = Super_L Super_R
                        !add Mod4 =
                        add Mod5 = Scroll_Lock
                        keycode 240 = p P
                        """)
        gtk.gdk.flush()
        mm = wimpiggy.keys.grok_modifier_map(self.display)
        keymap = gtk.gdk.keymap_get_for_display(self.display)

        o_keyval = gtk.gdk.keyval_from_name("o")
        o_keycode = keymap.get_entries_for_keyval(o_keyval)[0][0]

        assert wimpiggy.keys.parse_key("o", keymap, mm) == (0, [o_keycode])
        assert wimpiggy.keys.parse_key("O", keymap, mm) == (0, [o_keycode])
        assert wimpiggy.keys.parse_key("<alt>O", keymap, mm) == (8, [o_keycode])
        assert wimpiggy.keys.parse_key("<ALT>O", keymap, mm) == (8, [o_keycode])
        assert wimpiggy.keys.parse_key("<meTa>O", keymap, mm) == (8, [o_keycode])
        assert wimpiggy.keys.parse_key("<meTa><mod5>O", keymap, mm) == (8, [o_keycode])
        assert wimpiggy.keys.parse_key("<mod2>O", keymap, mm) == (16, [o_keycode])
        assert (wimpiggy.keys.parse_key("<mod4><mod3><MOD1><mod3>O", keymap, mm)
                == (8 | 32 | 64, [o_keycode]))

        p_keyval = gtk.gdk.keyval_from_name("p")
        p_keycodes = [entry[0]
                      for entry in keymap.get_entries_for_keyval(p_keyval)]
        assert len(p_keycodes) > 1
        assert wimpiggy.keys.parse_key("P", keymap, mm) == (0, p_keycodes)
        assert wimpiggy.keys.parse_key("<alt>p", keymap, mm) == (8, p_keycodes)

        assert wimpiggy.keys.unparse_key(0, o_keycode, keymap, mm) == "o"
        assert wimpiggy.keys.unparse_key(8, o_keycode, keymap, mm) == "<alt>o"
        assert wimpiggy.keys.unparse_key(16, o_keycode, keymap, mm) == "<mod2>o"
        assert wimpiggy.keys.unparse_key(32, o_keycode, keymap, mm) == "<super>o"
        assert (wimpiggy.keys.unparse_key(16 | 32, o_keycode, keymap, mm)
                == "<mod2><super>o")
        assert (wimpiggy.keys.unparse_key(8 | 32, o_keycode, keymap, mm)
                == "<super><alt>o")
        assert (wimpiggy.keys.unparse_key(1 | 2 | 4, o_keycode, keymap, mm)
                == "<shift><control>o")

    def test_HotkeyManager_end_to_end(self):
        self.clear_xmodmap()
        self.xmodmap("""add shift = Shift_L Shift_R
                        add lock = Caps_Lock
                        add control = Control_L Control_R
                        add Mod1 = Alt_L
                        add Mod2 = Num_Lock
                        add Mod4 = Super_L
                        """)

        print(1)
        root = self.display.get_default_screen().get_root_window()
        keymap = gtk.gdk.keymap_get_for_display(self.display)
        def keycode(name):
            keyval = gtk.gdk.keyval_from_name(name)
            return keymap.get_entries_for_keyval(keyval)[0][0]

        print(2)
        m = wimpiggy.keys.HotkeyManager(root)
        m.add_hotkeys({"<shift><alt>r": "shift-alt-r",
                       "<mod4>r": "mod4-r"})

        def press_unpress(keys):
            for k in keys:
                xtest_fake_key(self.display, keycode(k), True)
            for k in reversed(keys):
                xtest_fake_key(self.display, keycode(k), False)

        press_unpress(["Shift_L", "Alt_L", "r"])
        def shift_alt_r(obj, ev):
            assert ev == "shift-alt-r"
        print(3)
        assert_mainloop_emits(m, "hotkey::shift-alt-r", shift_alt_r)
        print(4)
        press_unpress(["Alt_L", "Shift_L", "r"])
        assert_mainloop_emits(m, "hotkey::shift-alt-r", shift_alt_r)

        press_unpress(["Super_L", "r"])
        def mod4_r(obj, ev):
            assert ev == "mod4-r"
        assert_mainloop_emits(m, "hotkey::mod4-r", mod4_r)

        # Now ones with nuisances in
        press_unpress(["Shift_L", "Caps_Lock", "Alt_L", "r"])
        assert_mainloop_emits(m, "hotkey::shift-alt-r", shift_alt_r)

        press_unpress(["Super_L", "Num_Lock", "r"])
        assert_mainloop_emits(m, "hotkey::mod4-r", mod4_r)

        # And make sure we handle changing modifier maps correctly
        print("Redoing modmap")
        self.clear_xmodmap()
        # We assert the keymap change is noticed mostly because it delays
        # further execution until the key change has a chance to propagate
        # from xmodmap, through the server, and back to us.
        assert_mainloop_emits(keymap, "keys-changed")
        self.xmodmap("""add shift = Shift_L Shift_R
                        add lock = Caps_Lock
                        add control = Control_L Control_R
                        add Mod1 = Super_L
                        add Mod2 = Num_Lock
                        add Mod4 = Alt_L
                        """)
        assert_mainloop_emits(keymap, "keys-changed")

        # Alt_L is now mod4, but this should still work:
        print("shift/alt/r?")
        press_unpress(["Shift_L", "Alt_L", "r"])
        assert_mainloop_emits(m, "hotkey::shift-alt-r", shift_alt_r)
        # And it should trigger the explicit mod4-version too
        print("mod4/r?")
        press_unpress(["Alt_L", "r"])
        assert_mainloop_emits(m, "hotkey::mod4-r", mod4_r)

        # FIXME: test del_hotkeys
