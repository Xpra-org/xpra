#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2020 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest

from xpra.util import AdHocStruct
from xpra.server.window.video_scoring import get_quality_score


class TestVideoScoring(unittest.TestCase):

    def test_score(self):
        csc_spec = AdHocStruct()
        csc_spec.quality = 10
        encoder_spec = AdHocStruct()
        encoder_spec.quality = 10
        encoder_spec.has_lossless_mode = True
        get_quality_score("YUV420P", csc_spec, encoder_spec, (1, 1))

def main():
    unittest.main()

if __name__ == '__main__':
    main()
