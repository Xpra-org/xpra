#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2020-2021 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

#pylint: disable=line-too-long

import unittest

from unit.test_util import LoggerSilencer
from xpra.sound import common


class TestCommon(unittest.TestCase):

    def test_sound_option(self):
        ONE_OPTION = [common.VORBIS, ]
        assert common.sound_option_or_all("unspecified", None, ONE_OPTION)==ONE_OPTION
        assert common.sound_option_or_all("unspecified", (), ONE_OPTION)==ONE_OPTION

        assert common.sound_option_or_all("valid", ONE_OPTION, ONE_OPTION)==ONE_OPTION
        with LoggerSilencer(common, ("error", "warn")):
            assert common.sound_option_or_all("invalid options", (common.VORBIS, common.OGG, ), ONE_OPTION)==ONE_OPTION
            assert common.sound_option_or_all("no valid options", (common.VORBIS, common.OGG, ), ())==[]


def main():
    unittest.main()

if __name__ == '__main__':
    main()
