#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import tempfile
import unittest

from xpra.os_util import POSIX
from xpra.util.objects import AdHocStruct
from xpra.net.mmap.common import DEFAULT_TOKEN_BYTES, MIN_SIZE
from xpra.net.mmap.io import init_client_mmap, write_mmap_token
from xpra.server.source import mmap as source_mmap
from xpra.server.source.mmap import MMAP_Connection

from unit.test_util import silence_warn, silence_error, silence_info


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
        source = make_source()
        allowed = source.allowed_dirs
        assert allowed, "no default mmap directory found"
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
        if not POSIX or not os.path.isdir("/run/user"):
            return
        # a peer belonging to another user is allowed to use that user's mmap directory:
        uid = os.getuid() + 1
        source = make_source(peer_uid=uid)
        peer_dir = f"/run/user/{uid}/xpra"
        self.assertIn(peer_dir, source.allowed_dirs)
        filename = f"{peer_dir}/xpra.1234.mmap"
        self.assertEqual(self.path(source, filename), filename)
        # our own directory is still allowed:
        assert len(source.allowed_dirs) >= 2
        # but not another user's:
        other = f"/run/user/{uid + 1}/xpra/xpra.1234.mmap"
        self.assertEqual(self.path(source, other), "")

    def test_unknown_peer_uid(self):
        if not POSIX:
            return
        # without a peer uid, only our own directory is allowed:
        source = make_source(peer_uid=-1)
        for mmap_dir in source.allowed_dirs:
            assert not mmap_dir.startswith("/run/user/") or str(os.getuid()) in mmap_dir


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


def main():
    unittest.main()


if __name__ == '__main__':
    main()
