#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2020 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

#pylint: disable=line-too-long

import unittest

from xpra.sound.common import (
    sound_option_or_all,
    VORBIS, OGG,
    log,
    )


class TestCommon(unittest.TestCase):

    def test_sound_option(self):
        ONE_OPTION = [VORBIS, ]
        assert sound_option_or_all("unspecified", None, ONE_OPTION)==ONE_OPTION
        assert sound_option_or_all("unspecified", (), ONE_OPTION)==ONE_OPTION

        assert sound_option_or_all("valid", ONE_OPTION, ONE_OPTION)==ONE_OPTION
        #suspend error logging:
        try:
            saved = log.error
            log.warn = log.debug
            assert sound_option_or_all("invalid options", (VORBIS, OGG, ), ONE_OPTION)==ONE_OPTION
            assert sound_option_or_all("no valid options", (VORBIS, OGG, ), ())==[]
        finally:
            log.error = saved


def main():
    unittest.main()

if __name__ == '__main__':
    main()
