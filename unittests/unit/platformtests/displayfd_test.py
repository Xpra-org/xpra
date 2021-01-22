#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2020 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import tempfile
import unittest

from xpra.os_util import load_binary_file
from xpra.platform.displayfd import write_displayfd, read_displayfd

class DisplayFDTest(unittest.TestCase):

    def test_write(self):
        temp = tempfile.NamedTemporaryFile(prefix="xpra.", suffix=".displayfd-test", delete=False)
        try:
            fd = temp.file.fileno()
            display = ":999"
            write_displayfd(fd, display)
            #read what was written:
            readback = load_binary_file(temp.name).decode().rstrip("\n")
            assert readback==display, "expected %s but got %s" % (display, readback)
            #file descriptor is already closed,
            #so this throws an exception
        finally:
            try:
                temp.close()
            except OSError:
                pass

    def test_read(self):
        display = ":999"
        try:
            f = tempfile.NamedTemporaryFile(prefix="xpra.", suffix=".displayfd-test", delete=False)
            f.write((display+"\n").encode())
            f.close()
            fd = os.open(f.name, os.O_RDONLY)
            d = read_displayfd(fd).decode().rstrip("\n")
            os.close(fd)
            assert d==display, "expected %s but got %s" % (display, d)
        finally:
            os.unlink(f.name)


def main():
    unittest.main()

if __name__ == '__main__':
    main()
