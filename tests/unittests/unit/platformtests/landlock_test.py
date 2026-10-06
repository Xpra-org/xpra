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

import xpra
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

    def test_file_and_socket_rules(self):
        import socket
        native = FakeNative()
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(landlock, "_get_native", return_value=native), socket.socket(socket.AF_UNIX) as sock:
            filename = os.path.join(directory, "cert")
            with open(filename, "w", encoding="utf8") as file:
                file.write("certificate")
            address = os.path.join(directory, "agent")
            sock.bind(address)
            landlock.restrict_paths((filename,), socket_paths=(address,))
        rules = dict(native.rules)
        self.assertEqual(rules[filename], landlock.FSAccess.EXECUTE | landlock.FSAccess.READ_FILE)
        self.assertEqual(rules[address], landlock.FSAccess.RESOLVE_UNIX)

    def test_missing_required_file(self):
        native = FakeNative()
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(landlock, "_get_native", return_value=native), self.assertRaises(FileNotFoundError):
            filename = os.path.join(directory, "missing")
            landlock.restrict_paths((filename,), required_paths=(filename,))
        self.assertIsNone(native.sync_threads)

    def test_mmap_paths_without_mmap_feature(self):
        from xpra.platform.posix.security import get_landlock_mmap_paths
        # `enforce_features` blocks the mmap modules when the feature is disabled, ie: `--minimal=yes`:
        with patch.dict(sys.modules, {"xpra.net.mmap": None, "xpra.net.mmap.common": None}):
            self.assertEqual(get_landlock_mmap_paths("/run/user/1000/xpra/mmap"), ())

    def run_native(self, script, *args, env=None):
        if not landlock.is_available() or landlock.get_abi_version() < 9:
            self.skipTest("Landlock ABI 9 native module is not available")
        subprocess.run((sys.executable, "-c", script, *args), check=True,
                       env={**os.environ, "PYTHONPATH": os.path.dirname(os.path.dirname(xpra.__file__)), **(env or {})})

    def test_strict_policy_threads_helpers_and_symlinks(self):
        script = r'''
import os, subprocess, sys, tempfile, threading
from types import SimpleNamespace
from xpra.client.base.landlock import LandLock
from xpra.common import noop
from xpra.platform.paths import get_mmap_dir
from xpra.scripts.config import make_defaults_struct
home, downloads, credential = sys.argv[1:]
secret = os.path.join(home, "secret")
ready = threading.Event()
results = []
def denied(path, mode):
    try:
        with open(path, mode):
            pass
    except PermissionError:
        return
    raise AssertionError("unexpected access to " + path)
def check():
    ready.wait()
    try:
        denied(secret, "r")
        denied(os.path.join(downloads, "escape"), "r")
        denied(os.path.join(home, "write"), "w")
        with open(credential) as file:
            assert file.read() == "certificate"
        with tempfile.TemporaryFile() as file:
            file.write(b"allowed")
        results.append(True)
    except BaseException as error:
        results.append(error)
old = threading.Thread(target=check)
old.start()
opts = make_defaults_struct()
opts.ssl_cert = credential
opts.landlock = "strict"
opts.download_path = downloads
client = SimpleNamespace(idle_add=noop, timeout_add=noop, source_remove=noop, subsystems={}, display_desc={})
landlock = LandLock(client)
landlock.init(opts)
landlock.run()
assert get_mmap_dir() == tempfile.gettempdir()
assert os.stat(tempfile.gettempdir()).st_mode & 0o777 == 0o700
ready.set()
new = threading.Thread(target=check)
new.start()
old.join()
new.join()
assert results == [True, True], results
denied("/tmp/xpra-landlock-shared-write-" + str(os.getpid()), "w")
result = subprocess.run([sys.executable, "-c", "import sys; open(sys.argv[1])", secret],
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE)
assert result.returncode != 0 and b"PermissionError" in result.stderr, result.stderr
with open(os.path.join(downloads, "received"), "w") as file:
    file.write("download")
private_temp = tempfile.gettempdir()
landlock.late_cleanup()
assert not os.path.exists(private_temp)
'''
        with tempfile.TemporaryDirectory() as directory:
            home = os.path.join(directory, "home")
            downloads = os.path.join(home, "Downloads")
            os.makedirs(downloads)
            secret = os.path.join(home, "secret")
            credential = os.path.join(home, "cert")
            for filename, data in ((secret, "private"), (credential, "certificate")):
                with open(filename, "w", encoding="utf8") as file:
                    file.write(data)
            os.symlink(secret, os.path.join(downloads, "escape"))
            self.run_native(script, home, downloads, credential, env={"HOME": home})
            self.assertCountEqual(os.listdir(downloads), ["escape", "received"])

    def test_strict_socket_resolution_and_cleanup(self):
        script = r'''
import os, socket, sys
from xpra.platform.posix.security import cleanup_landlock_temp_dir, enforce_landlock, prepare_landlock_temp_dir
root = sys.argv[1]
downloads = os.path.join(root, "downloads")
listeners = os.path.join(root, "listeners")
allowed = os.path.join(listeners, "allowed")
denied = os.path.join(root, "denied")
servers = []
for address in (allowed, denied):
    server = socket.socket(socket.AF_UNIX)
    server.bind(address)
    server.listen()
    servers.append(server)
temp_dir, temp_owner = prepare_landlock_temp_dir(downloads)
enforce_landlock("strict", (downloads,), socket_dirs=(listeners,), temp_dir=temp_dir, allow_socket_creation=False)
client = socket.socket(socket.AF_UNIX)
client.connect(allowed)
try:
    socket.socket(socket.AF_UNIX).connect(denied)
except PermissionError:
    pass
else:
    raise AssertionError("unexpected socket resolution")
try:
    socket.socket(socket.AF_UNIX).bind(os.path.join(downloads, "new"))
except PermissionError:
    pass
else:
    raise AssertionError("unexpected socket creation")
os.unlink(allowed)
cleanup_landlock_temp_dir(temp_dir, temp_owner)
'''
        with tempfile.TemporaryDirectory() as directory:
            os.mkdir(os.path.join(directory, "downloads"))
            os.mkdir(os.path.join(directory, "listeners"))
            self.run_native(script, directory)

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
                    env={**os.environ, "PYTHONPATH": os.path.dirname(os.path.dirname(xpra.__file__))},
                )


def main():
    unittest.main()


if __name__ == "__main__":
    main()
