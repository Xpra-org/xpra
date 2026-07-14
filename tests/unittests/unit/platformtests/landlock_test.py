#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import errno
import os
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from xpra.platform.posix import landlock


class FakeNative:
    def __init__(self, abi=9):
        self.abi = abi
        self.rules = []
        self.sync_threads = None

    def get_abi_version(self):
        return self.abi

    @staticmethod
    def create_ruleset(_access):
        return os.open(os.devnull, os.O_RDONLY)

    def add_path_rule(self, _ruleset_fd, parent_fd, access):
        self.rules.append((os.readlink(f"/proc/self/fd/{parent_fd}"), access))

    def restrict_self(self, _ruleset_fd, sync_threads):
        self.sync_threads = sync_threads


class LandlockTest(unittest.TestCase):

    def test_access_for_abi(self):
        self.assertNotIn(landlock.FSAccess.REFER, landlock.access_for_abi(1))
        self.assertIn(landlock.FSAccess.REFER, landlock.access_for_abi(2))
        self.assertIn(landlock.FSAccess.TRUNCATE, landlock.access_for_abi(3))
        self.assertIn(landlock.FSAccess.IOCTL_DEV, landlock.access_for_abi(5))
        self.assertNotIn(landlock.FSAccess.RESOLVE_UNIX, landlock.access_for_abi(8))
        self.assertIn(landlock.FSAccess.RESOLVE_UNIX, landlock.access_for_abi(9))

    def test_canonical_paths(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "subdir")
            os.mkdir(path)
            self.assertEqual(landlock.canonical_paths((path, path + "/../subdir")), (path, ))

    def test_rules_and_socket_creation(self):
        native = FakeNative()
        with tempfile.TemporaryDirectory() as tmpdir, \
             patch.object(landlock, "_get_native", return_value=native):
            abi = landlock.restrict_paths((tmpdir, ), (tmpdir, ),
                                          device_paths=(tmpdir, ),
                                          allow_socket_creation=False, sync_threads=True)
        self.assertEqual(abi, 9)
        self.assertTrue(native.sync_threads)
        self.assertEqual(len(native.rules), 1)
        access = landlock.FSAccess(native.rules[0][1])
        self.assertIn(landlock.FSAccess.WRITE_FILE, access)
        self.assertIn(landlock.FSAccess.IOCTL_DEV, access)
        self.assertNotIn(landlock.FSAccess.MAKE_SOCK, access)

    def test_device_access_does_not_grant_mutation(self):
        native = FakeNative()
        with tempfile.TemporaryDirectory() as tmpdir, \
             patch.object(landlock, "_get_native", return_value=native):
            landlock.restrict_paths(device_paths=(tmpdir, ))
        access = landlock.FSAccess(native.rules[0][1])
        self.assertIn(landlock.FSAccess.READ_FILE, access)
        self.assertIn(landlock.FSAccess.WRITE_FILE, access)
        self.assertIn(landlock.FSAccess.IOCTL_DEV, access)
        self.assertNotIn(landlock.FSAccess.MAKE_REG, access)
        self.assertNotIn(landlock.FSAccess.REMOVE_FILE, access)

    def test_old_abi_cannot_sync_threads(self):
        with patch.object(landlock, "_get_native", return_value=FakeNative(8)), \
             self.assertRaisesRegex(OSError, "ABI 9") as raised:
            landlock.restrict_paths(("/", ), sync_threads=True)
        self.assertEqual(raised.exception.errno, errno.EOPNOTSUPP)

    def test_native_policy(self):
        if not landlock.is_available() or landlock.get_abi_version() < 9:
            self.skipTest("Landlock ABI 9 native module is not available")
        script = r'''
import os, socket, sys
from xpra.platform.posix.landlock import restrict_paths
allowed, denied, make_socket = sys.argv[1:]
reads = (allowed, "/usr", "/etc", "/proc", "/sys", "/dev", "/run", "/var")
restrict_paths(reads, (allowed,), allow_socket_creation=make_socket == "1", sync_threads=True)
with open(os.path.join(allowed, "ok"), "w", encoding="utf8") as f:
    f.write("ok")
try:
    open(os.path.join(denied, "blocked"), "w", encoding="utf8")
except PermissionError:
    pass
else:
    raise SystemExit("write outside allowed root succeeded")
sock = socket.socket(socket.AF_UNIX)
try:
    sock.bind(os.path.join(allowed, "test.sock"))
except PermissionError:
    if make_socket == "1":
        raise
else:
    if make_socket != "1":
        raise SystemExit("pathname socket creation succeeded")
'''
        with tempfile.TemporaryDirectory() as tmpdir:
            allowed = os.path.join(tmpdir, "allowed")
            denied = os.path.join(tmpdir, "denied")
            os.mkdir(allowed)
            os.mkdir(denied)
            for make_socket in ("0", "1"):
                subprocess.run(
                    (sys.executable, "-c", script, allowed, denied, make_socket),
                    check=True,
                    env={**os.environ, "PYTHONPATH": os.getcwd()},
                )


def main():
    unittest.main()


if __name__ == "__main__":
    main()
