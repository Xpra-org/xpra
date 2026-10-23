#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys
import unittest
from types import ModuleType
from unittest.mock import patch

from xpra.config.info import get_build_info


class BuildInfoTest(unittest.TestCase):

    def test_supplied_build_and_source(self):
        source = ModuleType("xpra.src_info")
        source.REVISION, source.LOCAL_MODIFICATIONS, source.BRANCH, source.COMMIT = 123, 2, "master", "abc"
        build = ModuleType("xpra.build_info")
        build.build = {"type": "test", "machine": "machine", "by": "tester", "on": "host", "date": "date", "time": "time",
                       "cython": "test-cython", "compiler": "Optimizing Compiler Version test"}
        with patch.dict(sys.modules, {"xpra.src_info": source, "xpra.build_info": build}):
            lines = get_build_info()
        for expected in ("revision 123", "commit abc from master branch", "with 2 local changes", "test build",
                         "built on host by tester", "date time", "using Cython test-cython", "Optimizing Compiler", "Version test"):
            self.assertIn(expected, lines)
        self.assertIn(", machine", lines[0])

    def test_missing_information(self):
        with patch.dict(sys.modules, {"xpra.src_info": None, "xpra.build_info": None}), patch("xpra.config.warn") as warn:
            self.assertTrue(get_build_info()[0].startswith("Python "))
        self.assertEqual(warn.call_count, 2)

    def test_bit_fallback_and_unknown_modifications(self):
        source = ModuleType("xpra.src_info")
        source.REVISION, source.LOCAL_MODIFICATIONS, source.BRANCH, source.COMMIT = 123, "unknown", "", ""
        build = ModuleType("xpra.build_info")
        build.build = {"bit": "64bit"}
        with patch.dict(sys.modules, {"xpra.src_info": source, "xpra.build_info": build}):
            lines = get_build_info()
        self.assertIn(", 64bit", lines[0])
        self.assertFalse(any("local changes" in line for line in lines))


if __name__ == "__main__":
    unittest.main()
