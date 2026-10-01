#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import mmap
import shutil
import tempfile
import unittest

from xpra.os_util import WIN32, OSEnvContext
from xpra.util import typedict
from xpra.net import mmap_pipe
from xpra.net.mmap_pipe import (
    MmapPointerError,
    int_from_buffer, mmap_read, mmap_write, validate_chunks,
    read_mmap_token, write_mmap_token, init_server_mmap,
    )

from unit.test_util import silence_error, silence_info


SIZE = 4096
MIN_SIZE = 64*1024*1024


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
    def test_server_mmap_symlink(self):
        with tempfile.NamedTemporaryFile(prefix="xpra-mmap-test") as f:
            f.truncate(SIZE)
            f.flush()
            link = f.name+"-link"
            os.symlink(f.name, link)
            try:
                with silence_error(mmap_pipe):
                    area, size = init_server_mmap(link, SIZE)
                self.assertIsNone(area)
                self.assertEqual(size, 0)
                area, size = init_server_mmap(link, SIZE, follow_symlinks=True)
                self.assertEqual(size, SIZE)
                area.close()
            finally:
                os.unlink(link)

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

    def setUp(self):
        self.mmap_dir = tempfile.mkdtemp(prefix="xpra-mmap-dir-")
        self.other_dir = tempfile.mkdtemp(prefix="xpra-other-dir-")

    def tearDown(self):
        shutil.rmtree(self.mmap_dir)
        shutil.rmtree(self.other_dir)

    def make_file(self, dirname:str, token:int=0x1234, index:int=512) -> str:
        filename = os.path.join(dirname, "xpra.test.mmap")
        with open(filename, "wb") as f:
            f.truncate(MIN_SIZE)
        with open(filename, "r+b") as f:
            area = mmap.mmap(f.fileno(), MIN_SIZE)
            write_mmap_token(area, token, index)
            area.close()
        return filename

    def parse(self, filename:str, server_mmap_filename=None):
        from xpra.server.source import mmap as mmap_source
        c = mmap_source.MMAP_Connection()
        c.supports_mmap = True
        c.mmap_filename = server_mmap_filename
        c.min_mmap_size = MIN_SIZE
        c.init_state()
        with OSEnvContext():
            os.environ["XPRA_MMAP_DIR"] = self.mmap_dir
            with silence_info(mmap_source):
                c.parse_client_caps(typedict({
                    "mmap" : {
                        "file"          : filename,
                        "size"          : MIN_SIZE,
                        "token"         : 0x1234,
                        "token_index"   : 512,
                        },
                    }))
        return c

    def test_same_dir(self):
        c = self.parse(self.make_file(self.mmap_dir))
        self.assertEqual(c.mmap_size, MIN_SIZE)
        self.assertNotEqual(read_mmap_token(c.mmap, c.mmap_client_token_index), 0x1234)
        c.cleanup()

    def test_outside_dir(self):
        # the client cannot make the server open a file outside its mmap directory:
        filename = self.make_file(self.other_dir)
        c = self.parse(filename)
        self.assertEqual(c.mmap_size, 0)
        self.assertIsNone(c.mmap)
        # and the file has not been touched:
        with open(filename, "rb") as f:
            area = mmap.mmap(f.fileno(), MIN_SIZE, access=mmap.ACCESS_READ)
            self.assertEqual(area[:512], b"\0"*512)
            area.close()

    def test_symlink_in_dir(self):
        target = self.make_file(self.other_dir)
        os.symlink(target, os.path.join(self.mmap_dir, os.path.basename(target)))
        with silence_error(mmap_pipe):
            c = self.parse(target)
        self.assertEqual(c.mmap_size, 0)

    def test_server_path(self):
        # the administrator can point us anywhere, including through a symlink:
        target = self.make_file(self.other_dir)
        link = os.path.join(self.other_dir, "link.mmap")
        os.symlink(target, link)
        c = self.parse("/some/client/path", link)
        self.assertEqual(c.mmap_size, MIN_SIZE)
        c.cleanup()

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
