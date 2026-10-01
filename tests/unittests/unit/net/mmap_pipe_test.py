#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import mmap
import unittest

from xpra.net.mmap_pipe import (
    int_from_buffer, mmap_read, mmap_write, validate_chunks,
    )


SIZE = 4096


class MmapPipeTest(unittest.TestCase):

    @staticmethod
    def area():
        return mmap.mmap(-1, SIZE)

    def test_write_read_roundtrip(self):
        area = self.area()
        data = b"hello mmap"
        chunks, _free = mmap_write(area, SIZE, data)
        self.assertEqual(chunks, [(8, len(data))])
        rdata, free_cb = mmap_read(area, *chunks)
        self.assertEqual(bytes(rdata), data)
        free_cb()
        self.assertEqual(int_from_buffer(area, 0).value, 8+len(data))

    def test_invalid_chunks(self):
        area = self.area()
        for chunks in (
            (),
            ((0, 10), ),            # overlaps the control header
            ((-8, 10), ),           # negative offset
            ((8, -1), ),            # negative length
            ((8, SIZE), ),          # runs past the end of the area
            ((SIZE, 1), ),
            ((8, 10), (SIZE-4, 8)), # second chunk is out of range
            ((8, ), ),              # malformed
            (("8", 10), ),          # wrong type
            (8, ),
            ):
            with self.assertRaises(ValueError):
                validate_chunks(area, chunks)
            with self.assertRaises(ValueError):
                mmap_read(area, *chunks)
        validate_chunks(area, ((8, SIZE-8), ))



def main():
    unittest.main()


if __name__ == '__main__':
    main()
