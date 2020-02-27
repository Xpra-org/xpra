#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2020 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest
from xpra.codecs.nv_util import get_nvml_driver_version, get_proc_driver_version


class TestNVUtil(unittest.TestCase):

    def test_nvutil(self):
        v1 = get_nvml_driver_version()
        v2 = get_proc_driver_version()
        if v1 and v2:
            assert v1==v2

def main():
    unittest.main()

if __name__ == '__main__':
    main()
