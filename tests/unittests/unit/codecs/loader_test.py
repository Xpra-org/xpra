#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys
import unittest
from types import ModuleType
from unittest.mock import Mock, patch

from xpra.codecs import loader


class TestCodecVersion(unittest.TestCase):

    def test_alternate_version_function(self):
        module = ModuleType("xpra_test_codec_version")
        module.alternate_version = Mock(return_value="1.2.3")
        with patch.dict(sys.modules, {module.__name__: module}), patch.dict(loader.codec_versions, {}, clear=True):
            version = loader.add_codec_version("test", module.__name__, "missing()", "alternate_version()")
            self.assertEqual(version, "1.2.3")
            self.assertEqual(loader.codec_versions["test"], (1, 2, 3))
            module.alternate_version.assert_called_once_with()


if __name__ == '__main__':
    unittest.main()
