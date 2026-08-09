#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import mmap
import tempfile
import unittest

from xpra.os_util import WIN32
from xpra.net.mmap.common import DEFAULT_TOKEN_BYTES, MAX_TOKEN_BYTES, MIN_SIZE, MmapPointerError
from xpra.net.mmap import io
from xpra.net.mmap.io import (
    init_client_mmap, int_from_buffer, mmap_free_size, mmap_read, mmap_write,
    read_mmap_token, write_mmap_token, safe_open_mmap_file,
)

from unit.test_util import silence_warn, silence_error, silence_info


SIZE = 4096


class MmapIOTest(unittest.TestCase):

    @staticmethod
    def area():
        return mmap.mmap(-1, SIZE)

    def test_write_read_roundtrip(self):
        area = self.area()
        data = b"hello mmap"
        chunks = mmap_write(area, SIZE, data)
        self.assertEqual(chunks, ((8, len(data)), ))
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

    def test_init_client_mmap_directory(self):
        if WIN32:
            return
        # a directory can be specified instead of a filename:
        # the mmap file is then created in it, using a temporary filename
        with tempfile.TemporaryDirectory() as tmpdir:
            enabled, delete, area, size, tempfile_obj, filename = init_client_mmap(size=MIN_SIZE, filename=tmpdir)
            self.assertTrue(enabled)
            self.assertTrue(delete)
            self.assertGreaterEqual(size, MIN_SIZE)
            self.assertEqual(os.path.dirname(filename), tmpdir)
            self.assertEqual(os.listdir(tmpdir), [os.path.basename(filename)])
            area.close()
            # closing the temporary file removes it:
            tempfile_obj.close()
            self.assertEqual(os.listdir(tmpdir), [])

    def test_init_client_mmap_filename(self):
        if WIN32:
            return
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "test.mmap")
            enabled, _delete, area, size, tempfile_obj, filename = init_client_mmap(size=MIN_SIZE, filename=path)
            self.assertTrue(enabled)
            self.assertEqual(filename, path)
            self.assertIsNone(tempfile_obj)
            self.assertGreaterEqual(size, MIN_SIZE)
            area.close()
            # the file already exists now, so it is re-used as is:
            enabled, delete, area, size, _tempfile_obj, filename = init_client_mmap(size=MIN_SIZE, filename=path)
            self.assertTrue(enabled)
            self.assertFalse(delete)
            self.assertEqual(filename, path)
            area.close()
            os.unlink(path)

    def safe_open(self, tmpdir: str, filename: str, uids=()) -> int:
        with silence_warn(io), silence_error(io):
            return safe_open_mmap_file(tmpdir, filename, uids or (os.getuid(), ))

    def assert_refused(self, tmpdir: str, filename: str, uids=()) -> None:
        fd = self.safe_open(tmpdir, filename, uids)
        if fd >= 0:
            os.close(fd)
            raise AssertionError(f"{filename!r} should have been refused")

    def test_safe_open(self):
        if WIN32:
            return
        with tempfile.TemporaryDirectory() as tmpdir:
            def mkfile(name: str) -> str:
                path = os.path.join(tmpdir, name)
                with open(path, "wb") as f:
                    f.write(b"\0" * 1024)
                return path

            # a regular file we own can be used:
            mkfile("good.mmap")
            fd = self.safe_open(tmpdir, "good.mmap")
            assert fd >= 0, "a regular file should have been accepted"
            os.close(fd)
            # but not if we expect it to belong to someone else:
            self.assert_refused(tmpdir, "good.mmap", (os.getuid() + 1, ))
            # symbolic links are never followed, whatever they point at:
            os.symlink("/etc/passwd", os.path.join(tmpdir, "link.mmap"))
            self.assert_refused(tmpdir, "link.mmap")
            os.symlink(os.path.join(tmpdir, "good.mmap"), os.path.join(tmpdir, "link2.mmap"))
            self.assert_refused(tmpdir, "link2.mmap")
            # a hard link can point at a file we would have refused to open:
            os.link(os.path.join(tmpdir, "good.mmap"), os.path.join(tmpdir, "hard.mmap"))
            self.assert_refused(tmpdir, "hard.mmap")
            # only regular files:
            os.mkfifo(os.path.join(tmpdir, "fifo.mmap"))
            self.assert_refused(tmpdir, "fifo.mmap")
            os.mkdir(os.path.join(tmpdir, "subdir"))
            self.assert_refused(tmpdir, "subdir")
            # only a basename, so that no symlink can be followed on the way:
            self.assert_refused(tmpdir, "../../etc/passwd")
            self.assert_refused(tmpdir, "/etc/passwd")
            self.assert_refused(tmpdir, "subdir/good.mmap")
            self.assert_refused(tmpdir, "..")
            self.assert_refused(tmpdir, "")
            # and the file has to exist:
            self.assert_refused(tmpdir, "missing.mmap")

    def test_safe_open_directory_permissions(self):
        if WIN32:
            return
        with tempfile.TemporaryDirectory() as tmpdir:
            with open(os.path.join(tmpdir, "good.mmap"), "wb") as f:
                f.write(b"\0" * 1024)
            # a directory anyone can create files in is not safe,
            # unless the sticky bit prevents them from replacing our file:
            os.chmod(tmpdir, 0o777)
            self.assert_refused(tmpdir, "good.mmap")
            os.chmod(tmpdir, 0o1777)
            fd = self.safe_open(tmpdir, "good.mmap")
            assert fd >= 0, "a sticky directory should have been accepted"
            os.close(fd)

    def test_init_server_mmap_section(self):
        if not WIN32:
            return
        from xpra.net.mmap.io import init_server_mmap_section
        with silence_info(io), silence_error(io):
            # the name of a section that does not exist must not create one:
            self.assertEqual(init_server_mmap_section("xpra-does-not-exist", MIN_SIZE), (None, 0))
            # ie: the mmap file path of a client running on another system:
            self.assertEqual(init_server_mmap_section("/run/user/1000/xpra/xpra.test.mmap", MIN_SIZE), (None, 0))
            # the size is required:
            self.assertEqual(init_server_mmap_section("xpra-does-not-exist", 0), (None, 0))
            # a real client area can be found and mapped:
            enabled, _delete, area, size, _tempfile_obj, filename = init_client_mmap(size=MIN_SIZE)
            self.assertTrue(enabled)
            try:
                server_area, server_size = init_server_mmap_section(filename, size)
                self.assertIsNotNone(server_area)
                self.assertEqual(server_size, size)
                # verify that this really is the same memory:
                area.seek(8)
                area.write(b"hello mmap")
                server_area.seek(8)
                self.assertEqual(server_area.read(10), b"hello mmap")
                server_area.close()
                # but not using a size larger than the client's area:
                self.assertEqual(init_server_mmap_section(filename, size * 2), (None, 0))
            finally:
                area.close()
            # the section is gone once the client has closed it:
            self.assertEqual(init_server_mmap_section(filename, size), (None, 0))

    def test_unused_area_pointers(self):
        # a brand new area has both pointers set to zero:
        area = self.area()
        self.assertEqual(mmap_free_size(area, SIZE), SIZE - 8)
        self.assertEqual(mmap_write(area, SIZE, b"abc"), ((8, 3), ))


if __name__ == "__main__":
    unittest.main()
