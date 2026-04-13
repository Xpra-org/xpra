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


class MinimalFTH(FileTransferHandler):
    """Minimal concrete subclass with no-op send/compressed_wrapper for testing."""

    def __init__(self):
        super().__init__()
        self.sent: list = []
        self.init_attributes()

    def send(self, packet_type, *parts):
        self.sent.append((packet_type,) + parts)

    def compressed_wrapper(self, datatype, data, level=5):
        from xpra.net import compression
        return compression.Compressed(datatype, data)


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

    def test_parse_file_transfer_caps_ask_flags(self):
        fth = FileTransferHandler()
        fth.init_attributes()
        caps = typedict({"file": {"enabled": True, "ask": True, "open-ask": True, "open-url-ask": True,
                                  "chunks": 65536, "ask-timeout": 30}})
        fth.parse_file_transfer_caps(caps)
        self.assertTrue(fth.remote_file_transfer)
        self.assertTrue(fth.remote_file_transfer_ask)
        self.assertTrue(fth.remote_open_files_ask)
        self.assertTrue(fth.remote_open_url_ask)
        self.assertEqual(fth.remote_file_chunks, 65536)
        self.assertEqual(fth.remote_file_ask_timeout, 30)
        fth.cleanup()

    def test_parse_printer_caps(self):
        fth = FileTransferHandler()
        fth.init_attributes()
        caps = typedict({"file": {"printing": True, "printing-ask": True}})
        fth.parse_printer_caps(caps)
        self.assertTrue(fth.remote_printing)
        self.assertTrue(fth.remote_printing_ask)
        fth.cleanup()

    def test_parse_printer_caps_disabled(self):
        fth = FileTransferHandler()
        fth.init_attributes()
        fth.parse_printer_caps(typedict())
        self.assertFalse(fth.remote_printing)
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

    def test_get_info_contains_remote(self):
        fth = MinimalFTH()
        info = fth.get_info()
        self.assertIn("remote", info)
        remote = info["remote"]
        for key in ("file-transfer", "file-size-limit", "open-files", "open-url", "printing"):
            self.assertIn(key, remote)
        fth.cleanup()

    # ------------------------------------------------------------------
    # accept_data

    def test_accept_data_file_transfer_enabled(self):
        fth = MinimalFTH()
        fth.file_transfer = True
        ok, printit, openit = fth.accept_data("sid", "file", "hello.txt", False, False)
        self.assertTrue(ok)
        self.assertFalse(printit)
        self.assertFalse(openit)
        fth.cleanup()

    def test_accept_data_file_transfer_disabled(self):
        fth = MinimalFTH()
        fth.file_transfer = False
        ok, printit, openit = fth.accept_data("sid", "file", "hello.txt", False, False)
        self.assertFalse(ok)
        fth.cleanup()

    def test_accept_data_ask_blocks(self):
        # file_transfer_ask=True means we need explicit pre-approval
        fth = MinimalFTH()
        fth.file_transfer = True
        fth.file_transfer_ask = True
        ok, _, _ = fth.accept_data("unknown-id", "file", "f.txt", False, False)
        self.assertFalse(ok)
        fth.cleanup()

    def test_accept_data_pre_accepted(self):
        fth = MinimalFTH()
        fth.file_transfer = True
        fth.files_accepted["my-id"] = False
        ok, _, _ = fth.accept_data("my-id", "file", "f.txt", False, False)
        self.assertTrue(ok)
        # consumed on use
        self.assertNotIn("my-id", fth.files_accepted)
        fth.cleanup()

    def test_accept_data_openit_disabled(self):
        fth = MinimalFTH()
        fth.file_transfer = True
        fth.open_files = False
        ok, _, openit = fth.accept_data("sid", "file", "f.txt", False, True)
        self.assertTrue(ok)
        self.assertFalse(openit)
        fth.cleanup()

    # ------------------------------------------------------------------
    # send_open_url

    def test_send_open_url_blocked(self):
        fth = MinimalFTH()
        fth.init_attributes()
        fth.remote_open_url = False
        result = fth.send_open_url("https://example.com")
        self.assertFalse(result)
        self.assertEqual(fth.sent, [])
        fth.cleanup()

    def test_send_open_url_allowed(self):
        fth = MinimalFTH()
        fth.init_attributes()
        fth.remote_open_url = True
        fth.remote_open_url_ask = False
        result = fth.send_open_url("https://example.com")
        self.assertTrue(result)
        self.assertTrue(any(p[0] == "open-url" for p in fth.sent))
        fth.cleanup()

    # ------------------------------------------------------------------
    # send_file

    def test_send_file_transfer_disabled(self):
        fth = MinimalFTH()
        fth.file_transfer = False
        result = fth.send_file("f.txt", "", b"data", 4)
        self.assertFalse(result)
        fth.cleanup()

    def test_send_file_remote_not_supported(self):
        fth = MinimalFTH()
        fth.file_transfer = True
        fth.remote_file_transfer = False
        result = fth.send_file("f.txt", "", b"data", 4)
        self.assertFalse(result)
        fth.cleanup()

    def test_send_file_size_too_large(self):
        fth = MinimalFTH()
        fth.file_transfer = True
        fth.file_size_limit = 100
        fth.remote_file_transfer = True
        fth.remote_file_size_limit = 100
        result = fth.send_file("big.bin", "", b"x" * 200, 200)
        self.assertFalse(result)
        fth.cleanup()

    def test_send_file_success(self):
        fth = MinimalFTH()
        fth.file_transfer = True
        fth.file_size_limit = 10 * 1000 * 1000
        fth.remote_file_transfer = True
        fth.remote_file_size_limit = 10 * 1000 * 1000
        fth.remote_file_transfer_ask = False
        data = b"hello world"
        result = fth.send_file("hello.txt", "text/plain", data, len(data))
        self.assertTrue(result)
        self.assertTrue(any(p[0] == "send-file" for p in fth.sent))
        fth.cleanup()

    def test_send_file_print_disabled(self):
        fth = MinimalFTH()
        fth.printing = False
        result = fth.send_file("doc.pdf", "application/pdf", b"data", 4, printit=True)
        self.assertFalse(result)
        fth.cleanup()

    # ------------------------------------------------------------------
    # send_data_ask_timeout

    def test_send_data_ask_timeout_missing(self):
        fth = MinimalFTH()
        # should warn but not raise
        result = fth.send_data_ask_timeout("nonexistent-id")
        self.assertFalse(result)
        fth.cleanup()

    def test_send_data_ask_timeout_cleans_up(self):
        fth = MinimalFTH()
        fth.pending_send_data["my-id"] = SendPendingData(
            datatype="file", url="/tmp/f.txt", mimetype="", data=b"",
            filesize=0, printit=False, openit=False, options={},
        )
        fth.pending_send_data_timers["my-id"] = 0
        result = fth.send_data_ask_timeout("my-id")
        self.assertFalse(result)
        self.assertNotIn("my-id", fth.pending_send_data)
        fth.cleanup()

    # ------------------------------------------------------------------
    # cancel_download

    def test_cancel_download_not_found(self):
        fth = MinimalFTH()
        # should log error but not raise
        fth.cancel_download("unknown-send-id")
        fth.cleanup()

    def test_cancel_download_found(self):
        import hashlib
        import tempfile
        fth = MinimalFTH()
        tmp = tempfile.NamedTemporaryFile(delete=False)
        tmp.close()
        fd = os.open(tmp.name, os.O_RDWR)
        state = ReceiveChunkState(
            start=0.0, fd=fd, filename=tmp.name, mimetype="",
            printit=False, openit=False, filesize=0,
            options=typedict(), digest=hashlib.sha256(), written=0,
            cancelled=False, send_id="my-send-id", timer=0, chunk=0,
        )
        fth.receive_chunks_in_progress["chunk-abc"] = state
        fth.cancel_download("my-send-id")
        self.assertTrue(state.cancelled)
        fth.cleanup()

    # ------------------------------------------------------------------
    # do_process_file_data_request

    def test_do_process_file_data_request_file_transfer_disabled(self):
        fth = MinimalFTH()
        fth.file_transfer = False
        fth.do_process_file_data_request("file", "sid", "f.txt", 100, False, False, typedict())
        # should respond with False
        self.assertTrue(any(p[0] == "file-data-response" and p[2] is False for p in fth.sent))
        fth.cleanup()

    def test_do_process_file_data_request_url_disabled(self):
        fth = MinimalFTH()
        fth.open_url = False
        fth.do_process_file_data_request("url", "sid", "https://x.com", 0, False, False, typedict())
        self.assertTrue(any(p[0] == "file-data-response" and p[2] is False for p in fth.sent))
        fth.cleanup()

    def test_do_process_file_data_request_unknown_type(self):
        fth = MinimalFTH()
        fth.do_process_file_data_request("unknown-type", "sid", "x", 0, False, False, typedict())
        self.assertTrue(any(p[0] == "file-data-response" and p[2] is False for p in fth.sent))
        fth.cleanup()

    def test_do_process_file_data_request_pre_requested(self):
        fth = MinimalFTH()
        fth.file_transfer = True
        fth.files_requested["f.txt"] = True
        opts = typedict({"request-file": ("f.txt", True)})
        fth.do_process_file_data_request("file", "sid", "f.txt", 100, False, True, opts)
        self.assertTrue(any(p[0] == "file-data-response" and p[2] is True for p in fth.sent))
        fth.cleanup()


def main():
    unittest.main()


if __name__ == '__main__':
    main()
