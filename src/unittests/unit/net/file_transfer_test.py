#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2020 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import unittest

from xpra.util import typedict
from xpra.net.file_transfer import (
    basename, safe_open_download_file,
    FileTransferAttributes, FileTransferHandler,
    )


class TestVersionUtilModule(unittest.TestCase):

    def test_basename(self):
        def t(s, e):
            r = basename(s)
            assert r==e, "expected '%s' but got '%s' for '%s'" % (r, e, s)
        t("hello", "hello")
        t("/path/to/foo", "foo")
        t("\\other\\path\\bar", "bar")


    def test_safe_open(self):
        filename, fd = safe_open_download_file("hello", "application/pdf")
        try:
            dupe_filename, dupe_fd = safe_open_download_file("hello", "application/pdf")
            assert dupe_filename!=filename
            try:
                os.close(dupe_fd)
            finally:
                os.unlink(dupe_filename)
            os.close(fd)
        finally:
            os.unlink(filename)


    def test_file_transfer_attributes(self):
        fta = FileTransferAttributes()
        assert fta.get_file_transfer_features()
        assert fta.get_info()

    def test_file_transfer_handler(self):
        fth = FileTransferHandler()
        fth.init_attributes()
        assert fth.get_open_env()
        caps = typedict()
        fth.parse_file_transfer_caps(caps)
        assert fth.get_info()
        fth.check_digest("foo", "000", "000", "xor")
        try:
            fth.check_digest("foo", "000", "001", "sha1")
        except Exception:
            pass
        else:
            raise Exception("digest mismatch should trigger an exception!")
        fth.cleanup()


def main():
    unittest.main()

if __name__ == '__main__':
    main()
