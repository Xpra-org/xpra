#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2020 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import unittest

from xpra.platform import (
    program_context, threaded_server_init,
    get_application_name, get_prgname,
    )


class PlatformInitTest(unittest.TestCase):

    def test_all(self):
        threaded_server_init()
        with program_context() as f:
            assert repr(f)

        #this doesn't actually exercise more code,
        #as the attributes are initialized once per process...
        with program_context("prg") as f:
            assert repr(f)

        with program_context(None, "app") as f:
            assert repr(f)

        with program_context("prg", "app") as f:
            assert repr(f)
            assert get_application_name()=="app"
            assert get_prgname()=="prg"


def main():
    unittest.main()

if __name__ == '__main__':
    main()
