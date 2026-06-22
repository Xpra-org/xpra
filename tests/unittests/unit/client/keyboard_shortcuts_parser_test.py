#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import unittest
from unittest.mock import patch

from xpra.client.gui import keyboard_shortcuts_parser as parser


MODIFIERS = {"control": "control", "ctrl": "control", "shift": "shift", "meta": "mod1"}


class KeyboardShortcutsParserTest(unittest.TestCase):

    def test_modifier_names_and_defaults(self):
        names = parser.get_modifier_names({"Control_L": "control", "Alt_R": "mod1", "Caps_Lock": "lock"})
        self.assertEqual(names["ctrl"], "control")
        self.assertEqual(names["alt"], "mod1")
        self.assertNotIn("caps_lock", names)
        self.assertEqual(parser.parse_shortcut_modifiers("none", MODIFIERS), [])
        self.assertEqual(parser.parse_shortcut_modifiers("ctrl+shift", MODIFIERS), ["ctrl", "shift"])
        with patch.object(parser, "POSIX", True), patch.dict(os.environ, {"XDG_CURRENT_DESKTOP": "GNOME"}):
            self.assertEqual(parser.parse_shortcut_modifiers("auto", MODIFIERS), ["control", "shift"])
        self.assertTrue(parser.parse_shortcut_modifiers("invalid", MODIFIERS))

    def test_parse_args(self):
        self.assertEqual(parser.parse_args("'text', 2, 3.5, yes, off, None"),
                         ["text", 2, 3.5, True, False, None])
        with self.assertRaises(ValueError):
            parser.parse_args("not-an-int")

    def test_shortcuts_operations(self):
        shortcuts = parser.parse_shortcuts(("#+F1:first", "control+F1:second(1, 'x')"),
                                           ("meta", "shift"), MODIFIERS)
        self.assertEqual(shortcuts["F1"][0], (["mod1", "shift"], "first", []))
        self.assertEqual(shortcuts["F1"][1], (["control"], "second", [1, "x"]))
        replaced = parser.parse_shortcuts(("control+F1:first", "control+F1:replacement"), (), MODIFIERS)
        self.assertEqual(replaced["F1"], [(["control"], "replacement", [])])
        removed = parser.parse_shortcuts(("control+F1:first", "control+F1:_"), (), MODIFIERS)
        self.assertEqual(removed["F1"], [])

    def test_clear_invalid_and_default(self):
        self.assertIn("F4", parser.parse_shortcuts((), (), MODIFIERS))
        self.assertEqual(parser.parse_shortcuts(("control+F1:a", "clear"), (), MODIFIERS), {})
        self.assertEqual(parser.parse_shortcuts(("invalid", "bad+F1:a", "F2:call(bad)"), (), MODIFIERS), {})


if __name__ == "__main__":
    unittest.main()
