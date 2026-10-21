#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest
from unittest.mock import patch

from xpra.util import signal_emitter
from xpra.wayland.server.subsystem.manager import WaylandManager


class WaylandManagerSignalTest(unittest.TestCase):

    def emit_display_name(self, signal: str):
        # `SignalEmitter` checks the name on `connect()` as well as on `emit()`,
        # so a session which is working can still warn twice
        manager = WaylandManager()
        names = []
        with patch.object(signal_emitter, "log", wraps=signal_emitter.log) as log:
            manager.connect(signal, lambda _manager, name: names.append(name))
            manager.emit(signal, "wayland-9")
        return names, [call.args for call in log.warn.call_args_list]

    def test_display_name_is_declared(self):
        names, warnings = self.emit_display_name("display-name")
        self.assertEqual(names, ["wayland-9"])
        self.assertFalse(warnings, "the signal the manager emits should be declared")

    def test_an_undeclared_signal_still_warns(self):
        names, warnings = self.emit_display_name("display-nmae")
        self.assertEqual(names, ["wayland-9"])
        self.assertEqual(warnings, [
            ("Warning: %r is not a declared signal of %s", "display-nmae", "WaylandManager"),
        ] * 2)


def main():
    unittest.main()


if __name__ == '__main__':
    main()
