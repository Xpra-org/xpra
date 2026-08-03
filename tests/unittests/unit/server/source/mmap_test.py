#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import hashlib
import logging
import tempfile
import unittest

from xpra.os_util import POSIX
from xpra.util.objects import AdHocStruct, typedict
from xpra.net.mmap.common import DEFAULT_TOKEN_BYTES, get_mmap_dir
from xpra.net.mmap import io as mmap_io
from xpra.net.mmap.io import init_client_mmap, write_mmap_token
from xpra.server.source import mmap as source_mmap
from xpra.server.source.mmap import MMAP_Connection

from unit.test_util import silence_info, silence_error, silence_warn, LoggerSilencer


MIN_SIZE = 64 * 1024 * 1024


def make_source(mmap_filename: str = "", min_size: int = MIN_SIZE) -> MMAP_Connection:
    server = AdHocStruct()
    server.mmap_supported = True
    server.mmap_filename = mmap_filename
    server.mmap_min_size = min_size
    source = MMAP_Connection()
    source.init_from(None, server)
    source.init_state()
    return source


class ConfusedDeputyTest(unittest.TestCase):
    """
        Regression test for the mmap confused-deputy vulnerability:
        the server used to open whatever path the client named, verify the
        client's token, then write a fresh token of its own back into that file.
        A client that named a file with known contents could satisfy the token
        check and have the server corrupt an arbitrary file the server user owns.
        The fix confines a client-named file to the server's own mmap directory
        (by basename), so any path elsewhere is refused and left untouched.
    """

    # a fixed, predictable region the attacker forges a token for:
    TOKEN_INDEX = 4096
    KNOWN = bytes((i * 7 + 13) & 0xFF for i in range(DEFAULT_TOKEN_BYTES))

    def victim_file(self, directory: str, name: str = "victim.dat") -> str:
        # a MIN_SIZE file the server user owns, with known bytes at the token offset.
        # created sparse so the test stays cheap while still reporting a 64MB size:
        path = os.path.join(directory, name)
        fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            os.ftruncate(fd, MIN_SIZE)
            os.pwrite(fd, self.KNOWN, self.TOKEN_INDEX)
        finally:
            os.close(fd)
        self.addCleanup(lambda: os.path.exists(path) and os.unlink(path))
        return path

    def forged_caps(self, path: str) -> dict:
        # the token value the server reads at TOKEN_INDEX (little-endian):
        token = int.from_bytes(self.KNOWN, "little")
        area = {
            "enabled": True,
            "file": path,
            "size": MIN_SIZE,
            "token": token,
            "token_index": self.TOKEN_INDEX,
            "token_bytes": DEFAULT_TOKEN_BYTES,
        }
        # the server maps client "read"->write area(0) and "write"->read area(1),
        # so point both at the victim to exercise the write path either way:
        return {"mmap": {"read": dict(area), "write": dict(area)}}

    @staticmethod
    def digest(path: str) -> str:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        return h.hexdigest()

    def run_attack(self, source: MMAP_Connection, path: str) -> None:
        # drive the exact server flow: parse the hello (open+verify),
        # then build the reply (which is where the server writes its own token):
        # refusing the file legitimately logs an error (eg: ELOOP from O_NOFOLLOW),
        # so silence the io logger above ERROR to keep the test output clean:
        with silence_info(source_mmap), silence_error(source_mmap), silence_warn(source_mmap), \
                LoggerSilencer(mmap_io, "log", logging.CRITICAL):
            source.parse_client_caps(typedict(self.forged_caps(path)))
            source.get_caps()
            source.cleanup()

    def test_file_outside_mmap_dir_is_untouched(self):
        if not POSIX:
            return
        with tempfile.TemporaryDirectory() as elsewhere:
            # a unique basename that cannot exist in the server's mmap directory:
            name = f"victim.{os.getpid()}.dat"
            victim = self.victim_file(elsewhere, name)
            before = self.digest(victim)
            # no `mmap` override: a client naming a file outside the server's
            # own mmap directory must be refused outright, never opened:
            source = make_source()
            self.run_attack(source, victim)
            self.assertEqual(before, self.digest(victim), "the victim file was corrupted by the server")

    def test_symlink_is_untouched(self):
        if not POSIX:
            return
        # a symlink sitting in the server's mmap directory, pointing at a victim
        # elsewhere: O_NOFOLLOW must refuse it and leave the victim untouched.
        mmap_dir = get_mmap_dir()
        if not os.path.isdir(mmap_dir):
            return
        with tempfile.TemporaryDirectory() as hidden:
            victim = self.victim_file(hidden)
            before = self.digest(victim)
            link = os.path.join(mmap_dir, f"xpra.link.{os.getpid()}.mmap")
            os.symlink(victim, link)
            self.addCleanup(lambda: os.path.islink(link) and os.unlink(link))
            source = make_source()
            # the client names the symlink by basename (resolved into the mmap dir):
            self.run_attack(source, link)
            self.assertEqual(before, self.digest(victim), "the victim file was corrupted through a symlink")

    def test_legit_file_in_mmap_dir_is_accepted(self):
        # positive control: the default same-host client creates its area in the
        # server's mmap directory, so it must still be accepted after the fix.
        if not POSIX:
            return
        enabled, _delete, area, size, tempfile_obj, filename = init_client_mmap(size=MIN_SIZE, filename="")
        if not enabled:
            self.skipTest("could not create a client mmap area")
        self.addCleanup(area.close)
        if tempfile_obj:
            self.addCleanup(tempfile_obj.close)
        token, token_index = 0x123456789, 512
        write_mmap_token(area, token, token_index, DEFAULT_TOKEN_BYTES)
        caps = {
            "file": filename,
            "size": size,
            "token": token,
            "token_index": token_index,
            "token_bytes": DEFAULT_TOKEN_BYTES,
        }
        source = make_source()
        with silence_info(source_mmap):
            server_area = source.parse_area_caps("read", caps, 0)
        assert server_area and server_area.enabled, "a legit same-host mmap area should have been accepted"
        server_area.close()


def main():
    unittest.main()


if __name__ == '__main__':
    main()
