#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import unittest

from xpra.client.base import features
from xpra.client.base.features import set_client_features
from xpra.scripts.config import make_defaults_struct


class ClientFeaturesTest(unittest.TestCase):

    def test_tray_features_are_independent(self):
        old_enforce = os.environ.get("XPRA_ENFORCE_FEATURES")
        old_tray = features.tray
        old_systray = features.systray
        os.environ["XPRA_ENFORCE_FEATURES"] = "0"
        try:
            combinations = ((False, True), (True, False), (False, False), (True, True))
            for tray, systray in combinations:
                with self.subTest(tray=tray, systray=systray):
                    opts = make_defaults_struct()
                    opts.tray = tray
                    opts.system_tray = systray
                    set_client_features(opts)
                    self.assertEqual(features.tray, tray)
                    self.assertEqual(features.systray, systray)
                    from xpra.client.subsystem.window import get_window_client_base_classes
                    base_names = {base.__name__ for base in get_window_client_base_classes()}
                    self.assertEqual("WindowTray" in base_names, systray)
        finally:
            features.tray = old_tray
            features.systray = old_systray
            if old_enforce is None:
                os.environ.pop("XPRA_ENFORCE_FEATURES", None)
            else:
                os.environ["XPRA_ENFORCE_FEATURES"] = old_enforce


if __name__ == "__main__":
    unittest.main()
