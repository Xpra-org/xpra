#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest
from unittest.mock import patch

from xpra.client.subsystem import power as power_module
from xpra.client.subsystem.power import PowerEventClient


class PowerEventClientTest(unittest.TestCase):

    def setUp(self):
        self.power = PowerEventClient()
        self.signals: list[str] = []
        for signal in ("pause", "unpause"):
            self.power.connect(signal, lambda _power, s=signal: self.signals.append(s))

    def test_pause_unpause(self):
        power = self.power
        power.ui_pause()
        power.ui_pause()
        self.assertTrue(power.paused)
        power.ui_unpause()
        power.ui_unpause()
        self.assertFalse(power.paused)
        self.assertEqual(self.signals, ["pause", "unpause"], "state changes should only be emitted once")

    def test_platform_and_watcher_pause(self):
        # the platform pauses first, then the UI thread watcher notices the same stall:
        power = self.power
        power.platform_pause()
        self.assertTrue(power.platform_paused)
        power.ui_pause()
        power.ui_unpause()
        power.platform_unpause()
        self.assertFalse(power.platform_paused)
        self.assertFalse(power.paused)
        self.assertEqual(self.signals, ["pause", "unpause"])

    def ui_message_level(self) -> str:
        with patch.object(power_module, "log") as log:
            self.power.ui_message("UI thread is now blocked")
        if log.info.called:
            return "info"
        if log.called:
            return "debug"
        return ""

    def test_watcher_messages(self):
        self.assertEqual(self.ui_message_level(), "info")
        # the watcher pausing must not silence its own messages:
        self.power.ui_pause()
        self.assertEqual(self.ui_message_level(), "info")

    def test_expected_stall_messages(self):
        # the platform told us about the stall, the watcher's messages are just noise:
        self.power.platform_pause()
        self.assertEqual(self.ui_message_level(), "debug")
        self.power.platform_unpause()
        self.assertEqual(self.ui_message_level(), "info")
        self.power.suspended = 1.0
        self.assertEqual(self.ui_message_level(), "debug")


def main():
    unittest.main()


if __name__ == '__main__':
    main()
