#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2020 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import unittest

from xpra.util.objects import typedict
from xpra.net.file_transfer import (
    basename, safe_open_download_file,
    FileTransferAttributes, FileTransferHandler,
    get_open_env, digest_mismatch,
    ReceiveChunkState, SendChunkState, SendPendingData,
    DENY, ACCEPT, OPEN,
)


class TestBasename(unittest.TestCase):

    def test_simple(self):
        assert basename("hello") == "hello"

    def test_unix_path(self):
        assert basename("/path/to/foo") == "foo"

    def test_windows_path(self):
        assert basename("\\other\\path\\bar") == "bar"

    def test_mixed_separators(self):
        assert basename("/path/to\\mixed") == "mixed"

    def test_empty(self):
        assert basename("") == ""

    def test_trailing_sep(self):
        # trailing separator: result is empty string
        assert basename("/path/") == ""

    def test_no_sep(self):
        assert basename("justfilename.txt") == "justfilename.txt"


class TestSafeOpenDownloadFile(unittest.TestCase):

    def test_creates_file(self):
        filename, fd = safe_open_download_file("testfile", "")
        try:
            assert os.path.exists(filename)
            os.close(fd)
        finally:
            os.unlink(filename)

    def test_unique_filenames(self):
        filename, fd = safe_open_download_file("hello", "application/pdf")
        try:
            dupe_filename, dupe_fd = safe_open_download_file("hello", "application/pdf")
            assert dupe_filename != filename
            try:
                os.close(dupe_fd)
            finally:
                os.unlink(dupe_filename)
            os.close(fd)
        finally:
            os.unlink(filename)

    def test_pdf_extension(self):
        filename, fd = safe_open_download_file("report", "application/pdf")
        try:
            os.close(fd)
            assert filename.endswith(".pdf"), f"expected .pdf extension, got: {filename}"
        finally:
            os.unlink(filename)

    def test_postscript_extension(self):
        filename, fd = safe_open_download_file("doc", "application/postscript")
        try:
            os.close(fd)
            assert filename.endswith(".ps"), f"expected .ps extension, got: {filename}"
        finally:
            os.unlink(filename)

    def test_unknown_mimetype(self):
        filename, fd = safe_open_download_file("data", "application/octet-stream")
        try:
            os.close(fd)
        finally:
            os.unlink(filename)


class TestDigestMismatch(unittest.TestCase):

    def test_runs_without_error(self):
        import hashlib
        digest = hashlib.sha256(b"data")
        # just verify it doesn't raise
        digest_mismatch("somefile.bin", digest, "deadbeef")


class TestGetOpenEnv(unittest.TestCase):

    def test_has_xpra_key(self):
        env = get_open_env()
        assert "XPRA_XDG_OPEN" in env
        assert env["XPRA_XDG_OPEN"] == "1"

    def test_is_copy(self):
        env1 = get_open_env()
        env2 = get_open_env()
        assert env1 is not env2


class TestConstants(unittest.TestCase):

    def test_values(self):
        assert DENY == 0
        assert ACCEPT == 1
        assert OPEN == 2


class TestDataclasses(unittest.TestCase):

    def test_receive_chunk_state(self):
        import hashlib
        from xpra.util.objects import typedict as td
        state = ReceiveChunkState(
            start=0.0, fd=3, filename="f.bin", mimetype="raw",
            printit=False, openit=False, filesize=1024,
            options=td(), digest=hashlib.md5(), written=0,
            cancelled=False, send_id="abc", timer=0, chunk=0,
        )
        assert state.filename == "f.bin"
        assert state.filesize == 1024

    def test_send_chunk_state(self):
        state = SendChunkState(start=0.0, data=b"hello", chunk_size=65536, timer=0, chunk=0)
        assert state.data == b"hello"
        assert state.chunk_size == 65536

    def test_send_pending_data(self):
        pending = SendPendingData(
            datatype="file", url="/tmp/f", mimetype="raw",
            data=b"", filesize=0, printit=False, openit=True, options={},
        )
        assert pending.datatype == "file"
        assert pending.openit is True


class TestFileTransferAttributes(unittest.TestCase):

    def test_default_init(self):
        fta = FileTransferAttributes()
        assert fta.file_transfer is False
        assert fta.printing is False
        assert fta.open_files is False
        assert fta.open_url is False

    def test_get_info(self):
        fta = FileTransferAttributes()
        info = fta.get_info()
        assert "file" in info
        assert "printer" in info

    def test_get_file_transfer_features(self):
        fta = FileTransferAttributes()
        features = fta.get_file_transfer_features()
        assert "enabled" in features
        assert "size-limit" in features
        assert "chunks" in features

    def test_get_printer_features(self):
        fta = FileTransferAttributes()
        pf = fta.get_printer_features()
        assert "printing" in pf
        assert "printing-ask" in pf

    def test_init_attributes_enabled(self):
        fta = FileTransferAttributes()
        fta.init_attributes(file_transfer="yes", printing="yes", open_files="yes", open_url="yes")
        assert fta.file_transfer is True
        assert fta.printing is True
        assert fta.open_files is True
        assert fta.open_url is True

    def test_init_attributes_ask(self):
        fta = FileTransferAttributes()
        fta.init_attributes(file_transfer="ask", printing="ask", can_ask=True)
        assert fta.file_transfer_ask is True
        assert fta.printing_ask is True

    def test_init_attributes_ask_no_can_ask(self):
        fta = FileTransferAttributes()
        fta.init_attributes(file_transfer="ask", can_ask=False)
        assert fta.file_transfer_ask is False

    def test_file_size_limit(self):
        fta = FileTransferAttributes()
        fta.init_attributes(file_size_limit="10M")
        assert fta.file_size_limit == 10 * 1000 * 1000  # SI units: M = 1,000,000

    def test_open_command(self):
        fta = FileTransferAttributes()
        fta.init_attributes(open_command="xdg-open")
        assert fta.open_command == "xdg-open"

    def test_init_opts(self):
        from xpra.util.objects import AdHocStruct
        opts = AdHocStruct()
        opts.file_transfer = "yes"
        opts.file_size_limit = "1G"
        opts.printing = "no"
        opts.open_files = "no"
        opts.open_url = "no"
        opts.open_command = None
        fta = FileTransferAttributes()
        fta.init_opts(opts)
        assert fta.file_transfer is True


class TestFileTransferHandler(unittest.TestCase):

    def test_basic(self):
        fth = FileTransferHandler()
        fth.init_attributes()
        assert fth.get_info()
        fth.cleanup()

    def test_get_open_env(self):
        assert get_open_env()

    def test_parse_empty_caps(self):
        fth = FileTransferHandler()
        fth.init_attributes()
        fth.parse_file_transfer_caps(typedict())
        fth.cleanup()

    def test_parse_file_transfer_caps(self):
        fth = FileTransferHandler()
        fth.init_attributes()
        # parse_file_transfer_caps reads c.dictget("file"), so nest under "file":
        caps = typedict({"file": {"enabled": True, "size-limit": 1024 * 1024, "open": True, "open-url": True}})
        fth.parse_file_transfer_caps(caps)
        assert fth.remote_file_transfer
        fth.cleanup()

    def test_check_file_size_within_limit(self):
        fth = FileTransferHandler()
        fth.init_attributes("no", "10M")  # positional: file_transfer, file_size_limit
        # remote_file_size_limit defaults to 0; set it to match local so it doesn't block
        fth.remote_file_size_limit = fth.file_size_limit
        assert fth.check_file_size("send", "test.bin", 1024) is True
        fth.cleanup()

    def test_check_file_size_exceeds_local_limit(self):
        fth = FileTransferHandler()
        fth.init_attributes("no", "1000")  # 1000 bytes limit
        fth.remote_file_size_limit = fth.file_size_limit
        assert fth.check_file_size("send", "test.bin", 1024 * 1024) is False
        fth.cleanup()

    def test_check_file_size_exceeds_remote_limit(self):
        fth = FileTransferHandler()
        fth.init_attributes("no", "100M")
        fth.remote_file_size_limit = 1000  # remote allows only 1000 bytes
        assert fth.check_file_size("send", "test.bin", 1024 * 1024) is False
        fth.cleanup()

    def test_info_after_parse(self):
        fth = FileTransferHandler()
        fth.init_attributes("yes")  # positional: file_transfer
        caps = typedict({"file": {"enabled": True}})
        fth.parse_file_transfer_caps(caps)
        info = fth.get_info()
        assert isinstance(info, dict)
        fth.cleanup()


def main():
    unittest.main()


if __name__ == '__main__':
    main()
