#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2020 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import tempfile
import unittest

from xpra.notifications import common
from unit.test_util import silence_error


class TestCommon(unittest.TestCase):

    def test_parse_image_data(self):
        p = common.parse_image_data
        with silence_error(common):
            assert p(None) is None
            assert p((1, 2, 3)) is None
            assert p((1, 2, 3, 4, 5, 6, 7)) is None
        assert p((10, 10, 40, True, 32, 4, b"0"*40*10)) is not None
        assert p((10, 10, 40, False, 24, 4, b"0"*40*10)) is not None
        assert p((10, 10, 30, False, 24, 3, b"0"*30*10)) is not None

    def test_parse_image_path(self):
        iconname = "xpra"
        from xpra.platform.paths import get_icon_filename, get_icon_dir
        filename = get_icon_filename(iconname)
        if not filename:
            raise RuntimeError(f"no icon filename found for icon directory {get_icon_dir()} and icon name {iconname!r}")
        if not common.parse_image_path(filename):
            raise RuntimeError(f"failed to parse image path for filename {filename!r}, icon {iconname!r} and icon_dir={get_icon_dir()!r}")
        f = tempfile.NamedTemporaryFile(prefix="test-invalid-file", delete=False)
        try:
            f.file.write(b"0000000000000001111111111111111111111")
            f.file.flush()
            f.close()
            for x in ("", None, "/invalid-path", f.name):
                with silence_error(common):
                    try:
                        assert common.parse_image_path(x) is None
                    except TypeError:
                        pass
        finally:
            os.unlink(f.name)


def main():
    unittest.main()

if __name__ == '__main__':
    main()
