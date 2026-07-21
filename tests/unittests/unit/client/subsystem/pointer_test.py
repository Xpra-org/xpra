#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2019 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest

from xpra.util.objects import AdHocStruct
from unit.client.subsystem.clientmixintest_util import ClientMixinTest
from unit.process_test_util import DisplayContext


class PointerClientTest(ClientMixinTest):

    def test_pointer(self):
        from xpra.client.subsystem import pointer
        PointerClient = pointer.PointerClient
        opts = AdHocStruct()
        self._test_mixin_class(PointerClient, opts, {})
        display = AdHocStruct()
        display.get_monitor_relative_position = lambda _position: (2, 10, 20)
        self.subsystems = {"display": display}
        old_compat = pointer.BACKWARDS_COMPATIBLE
        pointer.BACKWARDS_COMPATIBLE = False
        try:
            self.assertEqual(
                self.mixin.split_pointer_position((100, 200, 5, 6)),
                (
                    (100, 200),
                    {
                        "window-position": (5, 6),
                        "monitor": {"index": 2, "position": (10, 20)},
                    },
                ),
            )
            self.assertEqual(
                self.mixin.split_pointer_position((100, 200)),
                (
                    (100, 200),
                    {"monitor": {"index": 2, "position": (10, 20)}},
                ),
            )
        finally:
            pointer.BACKWARDS_COMPATIBLE = old_compat
        pointer.BACKWARDS_COMPATIBLE = True
        try:
            self.assertEqual(
                self.mixin.split_pointer_position((100, 200, 5, 6)),
                (
                    (100, 200, 5, 6),
                    {
                        "window-position": (5, 6),
                        "monitor": {"index": 2, "position": (10, 20)},
                    },
                ),
            )
        finally:
            pointer.BACKWARDS_COMPATIBLE = old_compat
        self.glib.timeout_add(5000, self.stop)
        self.main_loop.run()


def main() -> None:
    with DisplayContext():
        unittest.main()


if __name__ == '__main__':
    main()
