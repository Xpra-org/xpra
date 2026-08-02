#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import mmap
import unittest

from xpra.net.mmap.common import DEFAULT_TOKEN_BYTES, MAX_TOKEN_BYTES, MmapPointerError
from xpra.net.mmap.io import (
    int_from_buffer, mmap_free_size, mmap_read, mmap_write,
    read_mmap_token, write_mmap_token,
)


SIZE = 4096


class MmapIOTest(unittest.TestCase):

    @staticmethod
    def area():
        return mmap.mmap(-1, SIZE)

    def test_invalid_token_range(self):
        area = self.area()
        for index, count in (
            (0, 2 ** 31),           # would take forever to read
            (0, 0),                 # no token at all
            (0, -1),                # negative size
            (0, MAX_TOKEN_BYTES + 1),
            (SIZE - 10, DEFAULT_TOKEN_BYTES),   # runs past the end of the area
            (-1, DEFAULT_TOKEN_BYTES),          # negative index
            (SIZE, 1),
        ):
            with self.assertRaises(ValueError):
                read_mmap_token(area, index, count)
            with self.assertRaises(ValueError):
                write_mmap_token(area, 0x1234, index, count)

    def test_token_roundtrip(self):
        area = self.area()
        for count in (1, DEFAULT_TOKEN_BYTES, MAX_TOKEN_BYTES):
            write_mmap_token(area, 0x12, 100, count)
            self.assertEqual(read_mmap_token(area, 100, count), 0x12)

    def test_write_read_roundtrip(self):
        area = self.area()
        data = b"hello mmap"
        chunks = mmap_write(area, SIZE, data)
        self.assertEqual(chunks, [(8, len(data))])
        rdata, free = mmap_read(area, *chunks)
        self.assertEqual(bytes(rdata), data)
        free()

    def test_wrapped_write_read_roundtrip(self):
        area = self.area()
        # fill up most of the area, so that the next write has to wrap around:
        mmap_write(area, SIZE, b"x" * (SIZE - 100))
        data = b"AB" * 40
        chunks = mmap_write(area, SIZE, data)
        rdata, free = mmap_read(area, *chunks)
        self.assertEqual(bytes(rdata), data)
        free()

    def test_invalid_chunks(self):
        area = self.area()
        for chunks in (
            ((0, 10), ),            # overlaps the control header
            ((8, -1), ),            # negative length
            ((-8, 16), ),           # negative offset
            ((SIZE - 4, 10), ),     # runs past the end of the area
            ((8, 16), (SIZE, 1)),   # second chunk is out of range
            ((8, ), ),              # not a pair
            (("a", "b"), ),         # not integers
            (8, ),                  # not a sequence
        ):
            with self.assertRaises(ValueError):
                mmap_read(area, *chunks)

    def test_invalid_pointers(self):
        area = self.area()
        for pos in (0, 4):
            for value in (7, SIZE + 1, 0xffffffff):
                int_from_buffer(area, pos).value = value
                with self.assertRaises(MmapPointerError):
                    mmap_write(area, SIZE, b"x" * 100)
                with self.assertRaises(MmapPointerError):
                    mmap_free_size(area, SIZE)
                int_from_buffer(area, pos).value = 8

    def test_unused_area_pointers(self):
        # a brand new area has both pointers set to zero:
        area = self.area()
        self.assertEqual(mmap_free_size(area, SIZE), SIZE - 8)
        self.assertEqual(mmap_write(area, SIZE, b"abc"), [(8, 3)])


if __name__ == "__main__":
    unittest.main()
