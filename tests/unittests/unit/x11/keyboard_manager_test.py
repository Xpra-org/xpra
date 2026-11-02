#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest
from contextlib import nullcontext
from unittest.mock import Mock, patch

from xpra.os_util import POSIX, OSX
from xpra.server.source.keyboard import KeyboardConnection


@unittest.skipUnless(POSIX and not OSX, "requires X11")
class X11KeyboardManagerTest(unittest.TestCase):

    @staticmethod
    def make_source(uuid, keyboard_input=True, record=False):
        source = KeyboardConnection()
        source.init_state()
        source.uuid = uuid
        source.keyboard_input = keyboard_input
        source.keyboard_record = record
        return source

    def test_only_input_clients_force_translation(self):
        from xpra.x11.subsystem import keyboard
        recorder = self.make_source("recorder", keyboard_input=False, record=True)
        interactive = self.make_source("interactive")
        recording_interactive = self.make_source("recording-interactive", record=True)
        for others, translate_only in (
            ([], False),
            ([recorder], False),
            ([interactive], True),
            ([recording_interactive], True),
            ([recorder, interactive], True),
        ):
            with self.subTest(others=others):
                source = self.make_source("new-client")
                source.keyboard_config = Mock(enabled=True)
                source.keyboard_config.get_hash.return_value = "new-layout"
                sources = [source, *others]
                server = Mock(readonly=False)
                server.get_sources_by_type.side_effect = lambda cls, exclude=None: tuple(
                    ss for ss in sources if isinstance(ss, cls) and ss is not exclude
                )
                manager = keyboard.X11KeyboardManager(server)
                manager.config_hash = "old-layout"
                # Keep the keymap-change timer and X11 error trap out of this unit test.
                manager.keymap_changing_timer = 1
                with patch.object(keyboard, "xsync", nullcontext()):
                    manager.set_keymap(source)
                source.keyboard_config.apply.assert_called_once_with(translate_only)
                self.assertIs(manager.config, source.keyboard_config)
                self.assertEqual(source.keyboard_config.owner, source.uuid)


if __name__ == "__main__":
    unittest.main()
