#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2020 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import tempfile
import unittest
from time import monotonic

from xpra.os_util import POSIX
from xpra.util.io import load_binary_file
from xpra.platform.displayfd import write_displayfd, read_displayfd, parse_displayfd, pipe_closed


class DisplayFDTest(unittest.TestCase):

    def test_parse(self):
        errors = []
        self.assertEqual(parse_displayfd(b"42\n", errors.append), 42)
        self.assertEqual(errors, [])
        for value in (b"", b"42", b"invalid\n", b"-1\n", b"65536\n"):
            with self.subTest(value=value):
                errors.clear()
                self.assertEqual(parse_displayfd(value, errors.append), -1)
                self.assertTrue(errors)

    def test_pipe_roundtrip(self):
        r_pipe, w_pipe = os.pipe()
        self.assertTrue(write_displayfd(w_pipe, "77"))
        try:
            self.assertEqual(read_displayfd(r_pipe), b"77\n")
        finally:
            os.close(r_pipe)

    def test_pipe_eof(self):
        for payload in (b"", b"77"):
            with self.subTest(payload=payload):
                r_pipe, w_pipe = os.pipe()
                os.write(w_pipe, payload)
                os.close(w_pipe)
                try:
                    start = monotonic()
                    self.assertEqual(read_displayfd(r_pipe, timeout=5), payload)
                    self.assertLess(monotonic() - start, 1, "EOF should return without waiting for the timeout")
                finally:
                    os.close(r_pipe)

    @unittest.skipUnless(POSIX, "select on pipes requires POSIX")
    def test_pipe_closed(self):
        r_pipe, w_pipe = os.pipe()
        with os.fdopen(r_pipe, "rb", buffering=0) as reader, os.fdopen(w_pipe, "wb", buffering=0) as writer:
            self.assertFalse(pipe_closed(reader.fileno()))
            writer.write(b"7")
            self.assertFalse(pipe_closed(reader.fileno()))
            writer.close()
            self.assertTrue(pipe_closed(reader.fileno()))
        self.assertTrue(pipe_closed(r_pipe))

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
        f = tempfile.NamedTemporaryFile(prefix="xpra.", suffix=".displayfd-test", delete=False)
        try:
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
