#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest
from unittest.mock import MagicMock, call, patch

from xpra.client.subsystem import power as power_module
from xpra.client.subsystem.power import PowerEventClient


class PowerEventClientTest(unittest.TestCase):

    def test_suspend_resume(self):
        for backwards_compatible in (False, True):
            with self.subTest(backwards_compatible=backwards_compatible), \
                    patch.object(power_module, "BACKWARDS_COMPATIBLE", backwards_compatible), \
                    patch.object(power_module, "time", return_value=100.0):
                power = PowerEventClient()
                power.emit = MagicMock()
                power.send = MagicMock()
                power.ui_watcher = MagicMock()
                power._id_to_window = {1: object()}
                # macos switching workspace without suspending first
                power.resume()
                power.emit.assert_not_called()
                power.send.assert_not_called()
                power.ui_watcher.tick.assert_not_called()
                power.suspend()
                self.assertTrue(power.suspended)
                power.resume()
                self.assertFalse(power.suspended)
                power.resume()
                self.assertEqual(power.emit.call_args_list, [call("suspend"), call("resume")])
                packet_args = (True, (1,)) if backwards_compatible else ()
                self.assertEqual(power.send.call_args_list, [
                    call("suspend", *packet_args),
                    call("resume", *packet_args),
                ])
                self.assertEqual(power.ui_watcher.tick.call_count, 2)


def main():
    unittest.main()


if __name__ == '__main__':
    main()
