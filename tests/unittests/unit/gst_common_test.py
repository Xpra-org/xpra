#!/usr/bin/env python3

import sys
import types
import unittest
from unittest.mock import Mock, patch

from xpra import gst_common


class GstCommonTest(unittest.TestCase):

    def setUp(self):
        self.saved_gst = gst_common.Gst
        gst_common.Gst = None
        self.addCleanup(setattr, gst_common, "Gst", self.saved_gst)

    @staticmethod
    def gi_modules(gst):
        gi = types.ModuleType("gi")
        gi.require_version = Mock()
        repository = types.ModuleType("gi.repository")
        repository.Gst = gst
        return {"gi": gi, "gi.repository": repository}

    def test_import_gst_uses_an_empty_argv(self):
        gst = Mock()
        with patch.dict(sys.modules, self.gi_modules(gst)):
            self.assertIs(gst_common.import_gst(), gst)
        gst.init.assert_called_once_with([])

    def test_import_gst_does_not_cache_a_failed_initialization(self):
        gst = Mock()
        gst.init.side_effect = TypeError("invalid argv")
        with patch.dict(sys.modules, self.gi_modules(gst)):
            self.assertIsNone(gst_common.import_gst())
        self.assertIsNone(gst_common.Gst)


if __name__ == "__main__":
    unittest.main()
