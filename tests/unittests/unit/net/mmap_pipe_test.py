#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import mmap
import tempfile
import unittest

from xpra.os_util import WIN32
from xpra.net import mmap_pipe
from xpra.net.mmap_pipe import (
    MmapPointerError,
    int_from_buffer, mmap_read, mmap_write, validate_chunks,
    init_server_mmap,
    )

from unit.test_util import silence_error


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

    def test_invalid_pointers(self):
        for pos in (0, 4):
            for value in (1, 7, SIZE+1, 2**32-1):
                area = self.area()
                int_from_buffer(area, pos).value = value
                with self.assertRaises(MmapPointerError):
                    mmap_write(area, SIZE, b"data")
        # the pointers can point at the very end of the area:
        area = self.area()
        int_from_buffer(area, 0).value = SIZE
        int_from_buffer(area, 4).value = SIZE
        chunks, _free = mmap_write(area, SIZE, b"data")
        self.assertEqual(chunks, [(8, 4)])

    @unittest.skipIf(WIN32, "posix only")
    def test_server_mmap_size(self):
        with tempfile.NamedTemporaryFile(prefix="xpra-mmap-test") as f:
            f.truncate(SIZE)
            f.flush()
            # mapping more than the file holds is refused:
            with silence_error(mmap_pipe):
                area, size = init_server_mmap(f.name, SIZE*2)
            self.assertIsNone(area)
            self.assertEqual(size, 0)
            # zero maps the whole file, and we get the real size:
            area, size = init_server_mmap(f.name, 0)
            self.assertEqual(size, SIZE)
            self.assertEqual(len(area), SIZE)
            area.close()


@unittest.skipIf(WIN32, "posix only")
class MmapConnectionTest(unittest.TestCase):

    def test_mmap_failure(self):
        from xpra.server.source import mmap as mmap_source
        c = mmap_source.MMAP_Connection()
        c.init_state()
        calls = []
        c.idle_add = lambda *args: calls.append(args)
        c.disconnect = None
        with silence_error(mmap_source):
            c.mmap_failure("test")
            c.mmap_failure("test again")
        self.assertEqual(len(calls), 1)


def main():
    unittest.main()


if __name__ == '__main__':
    main()
