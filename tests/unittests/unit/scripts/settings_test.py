#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest
from unittest.mock import Mock, patch

from xpra.scripts import settings
from xpra.scripts.config import InitException


class SettingsTest(unittest.TestCase):

    def test_value_formatting(self):
        self.assertEqual(settings.vstr(bool, None), "auto")
        self.assertEqual(settings.vstr(str, "a\nb"), "'a\\nb'")
        self.assertEqual(settings.vstr(str, ("a", "b")), "'a', 'b'")

    def test_set_values(self):
        update = Mock()
        option_types = {"daemon": bool, "compression_level": int, "start": list}
        with patch.object(settings, "OPTION_TYPES", option_types), \
                patch("xpra.util.config.update_config_attribute", update):
            self.assertEqual(settings.run_setting(True, ("daemon", "yes")), 0)
            update.assert_called_with("daemon", True)
            settings.run_setting(True, ("compression_level", "7"))
            update.assert_called_with("compression_level", 7)
            settings.run_setting(True, ("start", "xterm", "xclock"))
            update.assert_called_with("start", ("xterm", "xclock"))

    def test_unset_and_invalid_values(self):
        unset = Mock()
        with patch.object(settings, "OPTION_TYPES", {"daemon": bool}), \
                patch("xpra.util.config.unset_config_attribute", unset):
            self.assertEqual(settings.run_setting(False, ("daemon",)), 0)
            unset.assert_called_once_with("daemon")
            for setunset, args, error in (
                    (True, (), ValueError), (True, ("missing", "x"), ValueError),
                    (True, ("daemon",), InitException), (True, ("daemon", "maybe"), ValueError),
                    (True, ("daemon", "yes", "extra"), ValueError),
                    (False, ("daemon", "extra"), InitException)):
                with self.subTest(args=args), self.assertRaises(error):
                    settings.run_setting(setunset, args)

    def test_showsetting(self):
        logger = Mock()
        with patch.object(settings, "OPTION_TYPES", {"daemon": bool}), \
                patch.object(settings, "get_logger", return_value=logger), \
                patch.object(settings, "get_xpra_defaults_dirs", return_value=("/one",)), \
                patch.object(settings, "get_defaults", return_value={"daemon": True}), \
                patch.object(settings, "read_xpra_conf", return_value={"daemon": False}), \
                patch("xpra.platform.info.get_username", return_value="user"):
            self.assertEqual(settings.run_showsetting(("daemon", "invalid")), 0)
        self.assertGreaterEqual(logger.info.call_count, 4)
        logger.warn.assert_called_once()
        with self.assertRaises(InitException):
            settings.run_showsetting(())


if __name__ == "__main__":
    unittest.main()
