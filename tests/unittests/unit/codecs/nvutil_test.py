#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2020 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest


class TestNVUtil(unittest.TestCase):

    def test_nvutil(self):
        from xpra.codecs.nv_util import get_nvml_driver_version, get_proc_driver_version
        v1 = get_nvml_driver_version()
        v2 = get_proc_driver_version()
        if v1 and v2:
            assert v1==v2

def main():
    try:
        from xpra.codecs import nv_util
        assert nv_util
    except ImportError:
        print("nv_util codec not installed - test skipped")
    else:
        unittest.main()

if __name__ == '__main__':
    main()
