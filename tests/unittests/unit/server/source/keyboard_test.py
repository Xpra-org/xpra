#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest
from unittest.mock import patch

from xpra.server.source.keyboard import KeyboardConnection
from xpra.util.objects import typedict


class KeyboardConnectionTest(unittest.TestCase):

    def test_input_defaults_to_true(self):
        for caps in ({}, {"keyboard": True}, {"keyboard": {"enabled": True}}, {"keyboard": {"record": True}}):
            with self.subTest(caps=caps):
                source = KeyboardConnection()
                source.init_state()
                self.assertTrue(source.keyboard_input)
                with patch("xpra.server.source.keyboard.is_recording_allowed", return_value=True):
                    source.parse_client_caps(typedict(caps))
                self.assertTrue(source.keyboard_input)
                self.assertTrue(source.get_info()["keyboard"]["input"])

    def test_input_is_independent_of_recording_permission(self):
        for keyboard_input in (False, True):
            for allowed in (False, True):
                with self.subTest(keyboard_input=keyboard_input, allowed=allowed):
                    caps = typedict({"keyboard": {"input": keyboard_input, "record": True}})
                    self.assertTrue(KeyboardConnection.is_needed(caps))
                    source = KeyboardConnection()
                    source.init_state()
                    with patch("xpra.server.source.keyboard.is_recording_allowed", return_value=allowed) as permission:
                        source.parse_client_caps(caps)
                    permission.assert_called_once_with(source, "keyboard")
                    self.assertEqual(source.keyboard_input, keyboard_input)
                    self.assertEqual(source.keyboard_record, allowed)
                    self.assertEqual(source.get_info()["keyboard"]["input"], keyboard_input)


if __name__ == "__main__":
    unittest.main()
