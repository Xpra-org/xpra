#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import mmap
import os
import tempfile
import unittest
from unittest.mock import patch

from xpra.platform.posix import security


class FakeCall:
    def __init__(self, result=0):
        self.result = result
        self.calls = []
        self.argtypes = None
        self.restype = None

    def __call__(self, *args):
        self.calls.append(args)
        return self.result


class FakeLibC:
    def __init__(self, prctl_result=0, madvise_result=0):
        self.prctl = FakeCall(prctl_result)
        self.madvise = FakeCall(madvise_result)


class PosixSecurityTest(unittest.TestCase):

    def test_disable_ptrace(self):
        libc = FakeLibC()
        security.disable_ptrace(libc)
        self.assertEqual(libc.prctl.calls, [(security.PR_SET_DUMPABLE, 0, 0, 0, 0)])

    def test_disable_core_dumps(self):
        with patch.object(security.resource, "setrlimit") as setrlimit:
            security.disable_core_dumps()
        setrlimit.assert_called_once_with(security.resource.RLIMIT_CORE, (0, 0))

    def test_writable_private_mappings(self):
        data = """\
00400000-00401000 r--p 00000000 00:00 0 /program
00600000-00602000 rw-p 00000000 00:00 0 /program
10000000-10003000 rw-s 00000000 00:00 0 /shared
20000000-20004000 rw-p 00000000 00:00 0 [heap]
malformed rw-p 00000000 00:00 0
"""
        fd, path = tempfile.mkstemp()
        try:
            os.write(fd, data.encode("latin1"))
            os.close(fd)
            fd = -1
            self.assertEqual(list(security.writable_private_mappings(path)), [
                (0x00600000, 0x00602000),
                (0x20000000, 0x20004000),
            ])
        finally:
            if fd >= 0:
                os.close(fd)
            os.unlink(path)

    def test_mark_memory_nondumpable(self):
        libc = FakeLibC()
        with patch.object(mmap, "MADV_DONTDUMP", 16, create=True), \
             patch.object(security, "writable_private_mappings", return_value=iter(((0x1000, 0x3000),))):
            self.assertEqual(security.mark_memory_nondumpable(libc), (1, 0))
        self.assertEqual(libc.madvise.calls, [(0x1000, 0x2000, 16)])

    def test_harden_process(self):
        with patch.object(security, "disable_ptrace") as disable_ptrace, \
             patch.object(security, "disable_core_dumps") as disable_core_dumps, \
             patch.object(security, "mark_memory_nondumpable", return_value=(3, 0)) as dontdump:
            security.harden_process()
        disable_ptrace.assert_called_once_with()
        disable_core_dumps.assert_called_once_with()
        dontdump.assert_called_once_with()


def main():
    unittest.main()


if __name__ == "__main__":
    main()
