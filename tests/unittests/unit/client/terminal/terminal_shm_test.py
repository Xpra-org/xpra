#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Yan Shoshitaishvili <yans@pwn.college>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import unittest

try:
    from xpra.client.terminal import shm as terminal_shm
except ImportError:
    terminal_shm = None


@unittest.skipIf(terminal_shm is None, "the terminal client component is not available")
@unittest.skipUnless(terminal_shm is None or terminal_shm.ShmWriter.available(),
                     "no writable shared memory directory")
class ShmWriterTest(unittest.TestCase):

    def make_writer(self):
        writer = terminal_shm.ShmWriter()
        self.addCleanup(writer.cleanup)
        return writer

    def test_write_creates_a_readable_object(self):
        writer = self.make_writer()
        name = writer.write(b"\x01\x02\x03\x04" * 100)
        self.assertTrue(name.startswith("/xpra-terminal-"), name)
        # the name is what a `shm_open` caller uses, the object is a file here:
        path = writer.path(name)
        with open(path, "rb") as f:
            self.assertEqual(f.read(), b"\x01\x02\x03\x04" * 100)
        self.assertIn(name, writer.pending)

    def test_names_are_never_reused(self):
        writer = self.make_writer()
        names = {writer.write(b"x") for _ in range(10)}
        self.assertEqual(len(names), 10)

    def test_prune_forgets_consumed_objects(self):
        writer = self.make_writer()
        name = writer.write(b"consumed")
        # the terminal unlinks the objects it reads:
        os.unlink(writer.path(name))
        kept = writer.write(b"pending")
        self.assertNotIn(name, writer.pending)
        self.assertIn(kept, writer.pending)

    def test_cleanup_unlinks_leftovers(self):
        writer = self.make_writer()
        name = writer.write(b"leftover")
        path = writer.path(name)
        self.assertTrue(os.path.exists(path))
        writer.cleanup()
        self.assertFalse(os.path.exists(path))
        self.assertEqual(writer.pending, [])


def main():
    unittest.main()


if __name__ == "__main__":
    main()
