#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import unittest
from types import SimpleNamespace

from xpra.client.base.features import set_client_features
from xpra.server.features import set_server_features
from xpra.server.subsystem.control import ControlHandler
from xpra.scripts.config import make_defaults_struct
from xpra.scripts.parsing import parse_cmdline


class ControlOptionTest(unittest.TestCase):

    def test_defaults_use_auto(self):
        opts = make_defaults_struct()
        self.assertIsNone(opts.control)

    def test_parse_auto_value(self):
        opts, _args = parse_cmdline(["xpra", "start", "--control=auto"])
        self.assertIsNone(opts.control)

    def test_client_auto_disables_control(self):
        from xpra.client.base import features as client_features
        opts = make_defaults_struct()
        opts.control = None
        previous = client_features.control
        old = os.environ.get("XPRA_ENFORCE_FEATURES")
        os.environ["XPRA_ENFORCE_FEATURES"] = "0"
        try:
            set_client_features(opts)
            self.assertFalse(client_features.control)
        finally:
            client_features.control = previous
            if old is None:
                os.environ.pop("XPRA_ENFORCE_FEATURES", None)
            else:
                os.environ["XPRA_ENFORCE_FEATURES"] = old

    def test_server_auto_enables_control(self):
        from xpra.server import features as server_features
        opts = make_defaults_struct()
        opts.control = None
        previous = server_features.control
        try:
            set_server_features(opts, "encoder")
            self.assertTrue(server_features.control)
        finally:
            server_features.control = previous

    def test_server_control_subsystem_auto_enables(self):
        server = SimpleNamespace(hello_request_handlers={})
        handler = ControlHandler(server)
        opts = make_defaults_struct()
        opts.control = None
        handler.init(opts)
        self.assertTrue(handler.enabled)


if __name__ == "__main__":
    unittest.main()
