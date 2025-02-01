#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2020 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest

# pylint: disable=import-outside-toplevel


class TestNVUtil(unittest.TestCase):

    def test_nvutil(self) -> None:
        from xpra.codecs.nvidia.util import get_nvml_driver_version, get_proc_driver_version
        v1 = get_nvml_driver_version()
        v2 = get_proc_driver_version()
        if v1 and v2:
            assert v1 == v2, f"versions differ: {v1} (nvml) and {v2} (proc)"


def main():
    try:
        from xpra.codecs.nvidia import util
        assert util
    except ImportError:
        print("nvidia.util codec not installed - test skipped")
    else:
        unittest.main()


if __name__ == '__main__':
    main()
