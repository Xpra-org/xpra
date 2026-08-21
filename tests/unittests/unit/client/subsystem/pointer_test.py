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
        opts.mousewheel = "invert-y"
        self._test_mixin_class(PointerClient, opts, {})
        # the wheel map translates the vertical axis buttons:
        self.assertEqual(self.mixin.wheel_map[4], 5)
        self.assertEqual(self.mixin.wheel_map[5], 4)
        self.assertTrue(self.mixin.wheel_smooth)
        display = AdHocStruct()
        display.get_monitor_relative_position = lambda _position: (2, 10, 20)
        display.get_server_position = lambda position: (position[0] + 1920, position[1] + 1200)
        self.subsystems = {"display": display}
        old_compat = pointer.BACKWARDS_COMPATIBLE
        pointer.BACKWARDS_COMPATIBLE = False
        try:
            self.assertEqual(
                self.mixin.split_pointer_position((100, 200, 5, 6)),
                (
                    (2020, 1400),
                    {
                        "raw-position": (100, 200),
                        "window-position": (5, 6),
                        "monitor": {"index": 2, "position": (10, 20)},
                    },
                ),
            )
            self.assertEqual(
                self.mixin.split_pointer_position((100, 200)),
                (
                    (2020, 1400),
                    {
                        "raw-position": (100, 200),
                        "monitor": {"index": 2, "position": (10, 20)},
                    },
                ),
            )
        finally:
            pointer.BACKWARDS_COMPATIBLE = old_compat
        pointer.BACKWARDS_COMPATIBLE = True
        try:
            self.assertEqual(
                self.mixin.split_pointer_position((100, 200, 5, 6)),
                (
                    (2020, 1400, 5, 6),
                    {
                        "raw-position": (100, 200),
                        "window-position": (5, 6),
                        "monitor": {"index": 2, "position": (10, 20)},
                    },
                ),
            )
        finally:
            pointer.BACKWARDS_COMPATIBLE = old_compat
        self.glib.timeout_add(5000, self.stop)
        self.main_loop.run()

    def test_remote_pointer(self):
        from xpra.client.subsystem.pointer import PointerClient
        opts = AdHocStruct()
        opts.mousewheel = "on"
        self._test_mixin_class(PointerClient, opts, {})
        shown = []
        window = AdHocStruct()
        window.show_remote_pointer = lambda *args: shown.append(args)
        self.subsystems = {"window": window}
        # the server tells us where the pointer of another client is;
        # the overlay is drawn by the `window` subsystem, which we hand
        # our own pointer position (0, 0 in this harness):
        self.handle_packet(("pointer-position", 1, 100, 200, 5, 6))
        self.assertEqual(shown, [(1, 5, 6, 0, 0)])
        # the legacy packet carries no window relative position:
        self.handle_packet(("pointer-position", 1, 100, 200))
        self.assertEqual(shown[-1], (1, -1, -1, 0, 0))
        # `pointer-motion` has it as a property:
        self.handle_packet(("pointer-motion", -1, 1, 2, (100, 200), {"window-position": (7, 8)}))
        self.assertEqual(shown[-1], (2, 7, 8, 0, 0))
        # ..older servers packed it into the pointer data:
        self.handle_packet(("pointer-motion", -1, 1, 2, (100, 200, 9, 10), {}))
        self.assertEqual(shown[-1], (2, 9, 10, 0, 0))
        # ..and if it is missing there is nothing to show:
        self.handle_packet(("pointer-motion", -1, 1, 2, (100, 200), {}))
        self.assertEqual(len(shown), 4)
        # buttons and wheel events of the other clients are only logged:
        self.handle_packet(("pointer-button", -1, 1, 2, 1, True, (100, 200), {}))
        self.handle_packet(("pointer-wheel", 2, 4, 1000, (100, 200), (), (), {}))
        self.assertEqual(len(shown), 4)
        # a client without windows has nothing to draw the overlay on:
        self.subsystems = {}
        self.handle_packet(("pointer-position", 1, 100, 200, 5, 6))
        self.assertEqual(len(shown), 4)


def main() -> None:
    with DisplayContext():
        unittest.main()


if __name__ == '__main__':
    main()
