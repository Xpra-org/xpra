#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest
from types import SimpleNamespace

from xpra.client.base.record import RecordClient
from xpra.util.objects import typedict


class RecordKeyboardTest(unittest.TestCase):

    def test_recording_does_not_advertise_keyboard_input(self):
        client = SimpleNamespace(windows=True, encoding_options={})
        caps = typedict(RecordClient.make_hello(client))
        self.assertTrue(caps.boolget("keyboard.record"))
        self.assertFalse(caps.boolget("keyboard.input", True))


if __name__ == "__main__":
    unittest.main()
