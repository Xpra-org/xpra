#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2020 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest

from xpra.platform.features import main as features_main

class FeaturesTest(unittest.TestCase):

    def test_main(self):
        from xpra import util
        def noop(*_args):
            pass
        util.print_nested_dict = noop
        features_main()

def main():
    unittest.main()

if __name__ == '__main__':
    main()
