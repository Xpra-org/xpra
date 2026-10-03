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
from xpra.scripts.config import make_defaults_struct


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

    def test_strict_rejects_broad_directories(self):
        for path in ("/", os.path.expanduser("~"), os.path.dirname(os.path.expanduser("~")), "/tmp", "/var/tmp", "/dev/shm"):
            with self.subTest(path=path), self.assertRaisesRegex(ValueError, "dedicated directory"):
                security.check_landlock_directory(path)
        with tempfile.TemporaryDirectory() as directory:
            link = os.path.join(directory, "escape")
            os.symlink("/tmp", link)
            with self.assertRaises(ValueError):
                security.check_landlock_directory(link)

    def test_strict_read_roots(self):
        from xpra.platform.posix.landlock import canonical_paths
        paths = canonical_paths(security.get_strict_landlock_read_paths())
        for path in canonical_paths((os.path.expanduser("~"), os.getcwd(), "/tmp", "/var", "/run", "/dev", "/proc")):
            self.assertNotIn(path, paths)

    def test_strict_required_auth_file(self):
        opts = make_defaults_struct()
        with tempfile.TemporaryDirectory() as directory, \
             patch("xpra.platform.posix.landlock.restrict_paths") as restrict, \
             self.assertRaisesRegex(FileNotFoundError, "required Landlock resource"):
            opts.ssl_cert = os.path.join(directory, "missing")
            required = security.get_landlock_auth_paths(opts)
            security.enforce_landlock("strict", (directory,), read_paths=required, required_paths=required,
                                      allow_socket_creation=False)
        restrict.assert_not_called()

    def test_no_policy(self):
        with patch("xpra.platform.posix.landlock.restrict_paths") as restrict:
            self.assertEqual(security.enforce_landlock("no", allow_socket_creation=False), 0)
        restrict.assert_not_called()

    def test_private_temporary_directory(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ), \
             patch.object(tempfile, "tempdir", tempfile.tempdir):
            os.environ.pop("XPRA_LANDLOCK_TMP_DIR", None)
            path, owner = security.prepare_landlock_temp_dir(directory)
            self.assertEqual(owner, os.getpid())
            self.assertEqual(os.stat(path).st_mode & 0o777, 0o700)
            self.assertEqual(security.prepare_landlock_temp_dir(directory), (path, owner))
            self.assertEqual(tempfile.gettempdir(), path)
            os.environ["XPRA_LANDLOCK_TMP_OWNER"] = str(owner + 1)
            self.assertEqual(security.prepare_landlock_temp_dir(directory), (path, owner + 1))

    def test_private_temp_cleanup_preserves_parent_storage(self):
        with tempfile.TemporaryDirectory() as directory:
            owned = os.path.join(directory, "owned")
            parent = os.path.join(directory, "parent")
            os.mkdir(owned)
            os.mkdir(parent)
            security.cleanup_landlock_temp_dir(owned, os.getpid())
            security.cleanup_landlock_temp_dir(parent, os.getpid() + 1)
            self.assertFalse(os.path.exists(owned))
            self.assertTrue(os.path.exists(parent))

    def test_private_temp_cleanup_allows_reconnect(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ), \
             patch.object(tempfile, "tempdir", tempfile.tempdir):
            os.environ.pop("XPRA_LANDLOCK_TMP_DIR", None)
            path, owner = security.prepare_landlock_temp_dir(directory)
            security.cleanup_landlock_temp_dir(path, owner)
            self.assertFalse(os.path.exists(path))
            self.assertNotIn("XPRA_LANDLOCK_TMP_DIR", os.environ)
            self.assertNotIn("XPRA_LANDLOCK_TMP_OWNER", os.environ)
            self.assertIsNone(tempfile.tempdir)
            replacement, replacement_owner = security.prepare_landlock_temp_dir(directory)
            self.assertNotEqual(replacement, path)
            self.assertTrue(os.path.isdir(replacement))
            security.cleanup_landlock_temp_dir(replacement, replacement_owner)

    def test_forked_helper_preserves_parent_storage(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ), \
             patch.object(tempfile, "tempdir", tempfile.tempdir):
            os.environ.pop("XPRA_LANDLOCK_TMP_DIR", None)
            path, owner = security.prepare_landlock_temp_dir(directory)
            with patch.object(security.os, "getpid", return_value=os.getpid() + 1):
                security.cleanup_landlock_temp_dir(path, owner)
            self.assertTrue(os.path.isdir(path))
            self.assertEqual(os.environ["XPRA_LANDLOCK_TMP_DIR"], path)
            security.cleanup_landlock_temp_dir(path, owner)

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
