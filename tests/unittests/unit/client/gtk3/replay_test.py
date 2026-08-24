#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest

from xpra.client.gtk3.replay import GtkReplay
from xpra.scripts.config import make_defaults_struct


class GtkReplayTest(unittest.TestCase):

    def test_window_subsystems(self) -> None:
        replay = GtkReplay(make_defaults_struct())
        self.assertIs(replay.get_subsystem("display"), replay)
        self.assertIs(replay.get_subsystem("encoding"), replay)
        self.assertIsNotNone(replay.get_subsystem("pointer"))
        self.assertIsNotNone(replay.get_subsystem("window"))
        self.assertIsNone(replay.get_subsystem("missing"))


def main() -> None:
    unittest.main()


if __name__ == "__main__":
    main()
