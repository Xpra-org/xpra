#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import hashlib
import tempfile
import unittest
from contextlib import contextmanager

from xpra.os_util import POSIX
from xpra.util.env import OSEnvContext
from xpra.util.objects import AdHocStruct, typedict
from xpra.net.mmap.common import DEFAULT_TOKEN_BYTES, MIN_SIZE
from xpra.net.mmap.io import init_client_mmap, write_mmap_token
from xpra.server.source import mmap as source_mmap
from xpra.server.source.mmap import MMAP_Connection

from unit.test_util import silence_warn, silence_error, silence_info


@contextmanager
def temp_runtime_dir():
    """
        A throw-away `XDG_RUNTIME_DIR` so that the default mmap directories
        can be exercised even on hosts which have no runtime directory of their own
        (containers, CI images, and any session started without one).
        The directory is named after our uid - the standard `/run/user/$UID` layout -
        so that `get_runtime_dir` still returns a `$UID` template
        which can also be expanded for another user.
        Yields the parent directory: `{parent}/{uid}/xpra` is then our own mmap directory.
    """
    with tempfile.TemporaryDirectory() as parent:
        runtime_dir = os.path.join(parent, str(os.geteuid()))
        os.mkdir(runtime_dir, 0o700)
        with OSEnvContext(XDG_RUNTIME_DIR=runtime_dir):
            yield parent


def make_source(dirs=(), files=(), peer_uid=-1) -> MMAP_Connection:
    subsystem = AdHocStruct()
    subsystem.supported = True
    subsystem.dirs = dirs
    subsystem.files = files
    subsystem.min_size = 64 * 1024 * 1024
    server = AdHocStruct()
    server.subsystems = {"mmap": subsystem}
    conn = AdHocStruct()
    conn.get_peer_uid = lambda: peer_uid
    protocol = AdHocStruct()
    protocol._conn = conn
    source = MMAP_Connection()
    source.init_from(protocol, server)
    return source


class MmapPathTest(unittest.TestCase):

    def path(self, source: MMAP_Connection, filename: str, index: int = 0) -> str:
        with silence_warn(source_mmap):
            return source.mmap_path(filename, index)

    def test_files_override_the_client_path(self):
        # a file specified by the server is used as-is, for each area in turn:
        source = make_source(files=("/dev/shm/area0", "/dev/shm/area1"))
        self.assertEqual(self.path(source, "/tmp/client.mmap", 0), "/dev/shm/area0")
        self.assertEqual(self.path(source, "/tmp/client.mmap", 1), "/dev/shm/area1")
        # there is no file for the third area:
        self.assertEqual(self.path(source, "/tmp/client.mmap", 2), "")

    def test_server_directory(self):
        if not POSIX:
            return
        with tempfile.TemporaryDirectory() as d1, tempfile.TemporaryDirectory() as d2:
            source = make_source(dirs=(d1, d2))
            # the client's file is looked up in the directory it claims to be in:
            self.assertEqual(self.path(source, f"{d2}/client.mmap"), os.path.join(d2, "client.mmap"))
            # if we don't know the client's directory, the first one is used:
            self.assertEqual(self.path(source, "/tmp/client.mmap"), os.path.join(d1, "client.mmap"))
            # only the basename is ever used:
            self.assertEqual(self.path(source, "/tmp/../etc/passwd"), os.path.join(d1, "passwd"))

    def test_default_dirs_only(self):
        if not POSIX:
            return
        with temp_runtime_dir() as parent:
            source = make_source()
            allowed = source.allowed_dirs
            assert allowed, "no default mmap directory found"
            self.assertEqual(allowed[0], os.path.join(parent, str(os.getuid()), "xpra"))
            # a file in an allowed directory is accepted:
            filename = os.path.join(allowed[0], "xpra.1234.mmap")
            self.assertEqual(self.path(source, filename), filename)
            # anything else is refused:
            for filename in (
                "/etc/passwd",
                "/tmp/xpra.1234.mmap",
                os.path.expanduser("~/.ssh/id_rsa"),
                # the directory is only matched after normalization,
                # so traversal cannot be used to escape it:
                os.path.join(allowed[0], "..", "..", "etc", "passwd"),
            ):
                self.assertEqual(self.path(source, filename), "", f"{filename!r} should have been refused")

    def test_no_filename(self):
        source = make_source()
        self.assertEqual(self.path(source, ""), "")
        self.assertEqual(self.path(source, "/some/dir/"), "")

    def test_peer_uid_directory(self):
        if not POSIX:
            return
        # a peer belonging to another user is allowed to use that user's mmap directory:
        uid = os.getuid() + 1
        with temp_runtime_dir() as parent:
            source = make_source(peer_uid=uid)
            peer_dir = os.path.join(parent, str(uid), "xpra")
            self.assertIn(peer_dir, source.allowed_dirs)
            filename = f"{peer_dir}/xpra.1234.mmap"
            self.assertEqual(self.path(source, filename), filename)
            # our own directory is still allowed:
            assert len(source.allowed_dirs) >= 2
            # but not another user's:
            other = os.path.join(parent, str(uid + 1), "xpra", "xpra.1234.mmap")
            self.assertEqual(self.path(source, other), "")

    def test_unknown_peer_uid(self):
        if not POSIX:
            return
        # without a peer uid, only our own directory is allowed:
        with temp_runtime_dir() as parent:
            source = make_source(peer_uid=-1)
            self.assertEqual(tuple(source.allowed_dirs), (os.path.join(parent, str(os.getuid()), "xpra"), ))
            other = os.path.join(parent, str(os.getuid() + 1), "xpra", "xpra.1234.mmap")
            self.assertEqual(self.path(source, other), "")


class ParseAreaCapsTest(unittest.TestCase):
    """
        Exercises the whole server side path:
        the client creates a real mmap file and writes its token in it,
        the server has to find it, open it safely and verify the token.
    """

    def client_area(self, mmap_dir: str) -> tuple[dict, object]:
        enabled, _delete, area, size, tempfile_obj, filename = init_client_mmap(size=MIN_SIZE, filename=mmap_dir)
        assert enabled, "failed to create the client mmap area"
        self.addCleanup(area.close)
        if tempfile_obj:
            self.addCleanup(tempfile_obj.close)
        token = 0x123456789
        token_index = 512
        write_mmap_token(area, token, token_index, DEFAULT_TOKEN_BYTES)
        caps = {
            "file": filename,
            "size": size,
            "token": token,
            "token_index": token_index,
            "token_bytes": DEFAULT_TOKEN_BYTES,
        }
        return caps, area

    def test_client_area_is_accepted(self):
        if not POSIX:
            return
        with tempfile.TemporaryDirectory() as mmap_dir:
            caps, _area = self.client_area(mmap_dir)
            source = make_source(dirs=(mmap_dir, ))
            with silence_info(source_mmap):
                area = source.parse_area_caps("read", caps, 0)
            assert area, "the client's mmap area should have been accepted"
            assert area.enabled
            assert area.size >= MIN_SIZE
            area.close()

    def test_bad_token_is_refused(self):
        if not POSIX:
            return
        with tempfile.TemporaryDirectory() as mmap_dir:
            caps, _area = self.client_area(mmap_dir)
            caps["token"] += 1
            source = make_source(dirs=(mmap_dir, ))
            with silence_error(source_mmap):
                assert source.parse_area_caps("read", caps, 0) is None

    def test_symlink_is_refused(self):
        if not POSIX:
            return
        with tempfile.TemporaryDirectory() as mmap_dir, tempfile.TemporaryDirectory() as hidden:
            caps, _area = self.client_area(hidden)
            # the same file, reached through a symlink in an allowed directory:
            link = os.path.join(mmap_dir, "xpra.link.mmap")
            os.symlink(caps["file"], link)
            caps["file"] = link
            source = make_source(dirs=(mmap_dir, ))
            with silence_error(source_mmap), silence_warn(source_mmap):
                assert source.parse_area_caps("read", caps, 0) is None

    def test_file_outside_the_allowed_directory_is_refused(self):
        if not POSIX:
            return
        with tempfile.TemporaryDirectory() as mmap_dir, tempfile.TemporaryDirectory() as other:
            caps, _area = self.client_area(other)
            # the server only allows `mmap_dir`, and there is no such file in it:
            source = make_source(dirs=(mmap_dir, ))
            with silence_error(source_mmap), silence_warn(source_mmap):
                assert source.parse_area_caps("read", caps, 0) is None


class ConfusedDeputyTest(unittest.TestCase):
    """
        Regression test for the mmap confused-deputy vulnerability
        (present up to and including 6.5.x):
        the server used to open whatever path the client named, verify the
        client's token, then write a fresh token of its own back into that file.
        A client that named a file with known contents could satisfy the token
        check and have the server corrupt an arbitrary file the server user owns.
        Here the malicious client forges a matching token and we assert that the
        victim file is left byte-for-byte unchanged.
    """

    # a fixed, predictable region the attacker can forge a token for:
    TOKEN_INDEX = 4096
    KNOWN = bytes((i * 7 + 13) & 0xFF for i in range(DEFAULT_TOKEN_BYTES))

    def victim_file(self, mmap_dir: str) -> str:
        # a MIN_SIZE file the server user owns, with known bytes at the token offset.
        # created sparse so the test stays cheap while still reporting a 64MB size:
        path = os.path.join(mmap_dir, "victim.dat")
        fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            os.ftruncate(fd, MIN_SIZE)
            os.pwrite(fd, self.KNOWN, self.TOKEN_INDEX)
        finally:
            os.close(fd)
        self.addCleanup(lambda: os.path.exists(path) and os.unlink(path))
        return path

    def forged_caps(self, victim: str) -> dict:
        # the token value the server will read at TOKEN_INDEX (little-endian, per read_mmap_token):
        token = int.from_bytes(self.KNOWN, "little")
        area = {
            "enabled": True,
            "file": victim,
            "size": MIN_SIZE,
            "token": token,
            "token_index": self.TOKEN_INDEX,
            "token_bytes": DEFAULT_TOKEN_BYTES,
        }
        # the server maps client "read"->write area(0) and "write"->read area(1),
        # so point both at the victim to exercise the write path regardless of the swap:
        return {"mmap": {"read": dict(area), "write": dict(area)}}

    @staticmethod
    def digest(path: str) -> str:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        return h.hexdigest()

    def run_attack(self, source: MMAP_Connection, victim: str) -> None:
        # drive the exact server flow: parse the hello (open+verify),
        # then build the reply (which is where the server writes its own token):
        with silence_info(source_mmap), silence_error(source_mmap), silence_warn(source_mmap):
            source.parse_client_caps(typedict(self.forged_caps(victim)))
            source.get_caps()
            source.cleanup()

    def test_file_outside_allowed_dirs_is_untouched(self):
        if not POSIX:
            return
        with tempfile.TemporaryDirectory() as elsewhere:
            victim = self.victim_file(elsewhere)
            before = self.digest(victim)
            # the default allow-list only covers the server's own mmap directory,
            # so a client naming a file anywhere else must be rejected outright:
            source = make_source()
            assert not any(os.path.normpath(d) == os.path.normpath(elsewhere) for d in source.allowed_dirs)
            self.run_attack(source, victim)
            self.assertEqual(before, self.digest(victim), "the victim file was corrupted by the server")

    def test_symlink_into_allowed_dir_is_untouched(self):
        if not POSIX:
            return
        with tempfile.TemporaryDirectory() as allowed, tempfile.TemporaryDirectory() as hidden:
            victim = self.victim_file(hidden)
            before = self.digest(victim)
            # the same file, reached through a symlink that does sit in an allowed directory:
            link = os.path.join(allowed, "victim.dat")
            os.symlink(victim, link)
            source = make_source(dirs=(allowed, ))
            self.run_attack(source, link)
            self.assertEqual(before, self.digest(victim), "the victim file was corrupted through a symlink")


def main():
    unittest.main()


if __name__ == '__main__':
    main()
