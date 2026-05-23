#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest
from unittest.mock import patch

from xpra.exit_codes import ExitCode
from xpra.server.glib_server import GLibServer


class TestGLibServer(unittest.TestCase):

    def test_run_handles_keyboard_interrupt(self):
        class KeyboardInterruptServer(GLibServer):
            def __init__(self):
                super().__init__()
                self.cleaned = False

            def server_is_ready(self):
                pass

            def do_run(self):
                raise KeyboardInterrupt()

            def cleanup(self):
                self.cleaned = True

        server = KeyboardInterruptServer()
        with patch("xpra.server.glib_server.GLib.idle_add"):
            assert server.run() == ExitCode.OK
        assert server.cleaned is True


def main():
    unittest.main()


if __name__ == "__main__":
    main()
