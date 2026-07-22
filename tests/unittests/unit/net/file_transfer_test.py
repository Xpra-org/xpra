#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2020 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import errno
import itertools
import stat
import unittest
import tempfile
from unittest.mock import MagicMock, patch
from time import monotonic

from xpra.net.common import Packet
from xpra.util.objects import typedict
from xpra.net import file_transfer
from xpra.net.file_transfer import (
    basename, safe_open_download_file,
    FileTransferAttributes, FileTransferHandler,
    get_open_env, digest_mismatch,
    AcceptedData, AcceptedDataRequest, ReceiveChunkState, RequestedFile, SendChunkState, SendPendingData,
    DENY, ACCEPT, OPEN,
)

_orig_file_io_thread = file_transfer.FILE_IO_THREAD


def setUpModule() -> None:
    # run the file-transfer handlers inline (synchronously) instead of handing off
    # to the file worker thread, so these logic tests can assert their results
    # directly, without a running main loop to start and drain that thread.
    # The worker hand-off itself is covered by `unit/seccomp_test.py`.
    file_transfer.FILE_IO_THREAD = False


def tearDownModule() -> None:
    file_transfer.FILE_IO_THREAD = _orig_file_io_thread


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

    def test_unicode(self):
        filename = "r\u00e9sum\u00e9-\u65e5\u672c\u8a9e-\U0001f4c4.txt"
        assert basename(f"/downloads/{filename}") == filename
        assert basename(f"C:\\downloads\\{filename}") == filename


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

    def test_unicode_filename(self):
        basefilename = "r\u00e9sum\u00e9-\u65e5\u672c\u8a9e-\U0001f4c4.pdf"
        with tempfile.TemporaryDirectory() as download_dir, \
             patch("xpra.platform.paths.get_download_dir", return_value=download_dir):
            filename, fd = safe_open_download_file(basefilename, "application/pdf")
            os.close(fd)
            self.assertEqual(os.path.basename(filename), basefilename)
            self.assertTrue(os.path.exists(filename))

    def test_special_names_stay_in_download_directory(self):
        with tempfile.TemporaryDirectory() as download_dir, \
             patch("xpra.platform.paths.get_download_dir", return_value=download_dir):
            for basefilename in ("", ".", "..", "../..", "/"):
                with self.subTest(basefilename=basefilename):
                    filename, fd = safe_open_download_file(basefilename, "")
                    os.close(fd)
                    self.assertEqual(os.path.commonpath((download_dir, filename)), download_dir)
                    self.assertTrue(os.path.basename(filename).startswith("download"))

    def test_remote_paths_are_reduced_to_basename(self):
        with tempfile.TemporaryDirectory() as download_dir, \
             patch("xpra.platform.paths.get_download_dir", return_value=download_dir):
            filename, fd = safe_open_download_file("../../outside.txt", "")
            os.close(fd)
            self.assertEqual(filename, os.path.join(download_dir, "outside.txt"))

    def test_collisions_preserve_extension(self):
        with tempfile.TemporaryDirectory() as download_dir, \
             patch("xpra.platform.paths.get_download_dir", return_value=download_dir):
            os.mkdir(os.path.join(download_dir, "report.pdf"))
            filename, fd = safe_open_download_file("report.pdf", "application/pdf")
            os.close(fd)
            self.assertEqual(filename, os.path.join(download_dir, "report-1.pdf"))

    def test_symlink_collisions_are_not_followed(self):
        with tempfile.TemporaryDirectory() as root:
            download_dir = os.path.join(root, "downloads")
            os.mkdir(download_dir)
            victim = os.path.join(root, "victim")
            with open(victim, "wb") as f:
                f.write(b"do not overwrite")
            link = os.path.join(download_dir, "report.pdf")
            try:
                os.symlink(victim, link)
            except OSError as e:
                self.skipTest(f"symlinks are unavailable: {e}")
            with patch("xpra.platform.paths.get_download_dir", return_value=download_dir):
                filename, fd = safe_open_download_file("report.pdf", "application/pdf")
                os.close(fd)
            self.assertEqual(filename, os.path.join(download_dir, "report-1.pdf"))
            with open(victim, "rb") as f:
                self.assertEqual(f.read(), b"do not overwrite")

    def test_broken_symlink_collision_is_not_replaced(self):
        with tempfile.TemporaryDirectory() as download_dir:
            link = os.path.join(download_dir, "broken.txt")
            try:
                os.symlink(os.path.join(download_dir, "missing-target"), link)
            except OSError as e:
                self.skipTest(f"symlinks are unavailable: {e}")
            with patch("xpra.platform.paths.get_download_dir", return_value=download_dir):
                filename, fd = safe_open_download_file("broken.txt", "")
                os.close(fd)
            self.assertTrue(os.path.islink(link))
            self.assertEqual(filename, os.path.join(download_dir, "broken-1.txt"))

    def test_creation_race_uses_next_available_name(self):
        real_open = os.open
        raced = False

        def racing_open(filename, flags, mode=0o777):
            nonlocal raced
            if not raced:
                raced = True
                race_fd = real_open(filename, flags, mode)
                os.close(race_fd)
                raise FileExistsError(errno.EEXIST, "simulated creation race", filename)
            return real_open(filename, flags, mode)

        with tempfile.TemporaryDirectory() as download_dir, \
             patch("xpra.platform.paths.get_download_dir", return_value=download_dir), \
             patch("xpra.net.file_transfer.os.open", side_effect=racing_open):
            filename, fd = safe_open_download_file("race.txt", "")
            os.close(fd)
            self.assertEqual(filename, os.path.join(download_dir, "race-1.txt"))

    @unittest.skipUnless(os.name == "posix", "POSIX permissions required")
    def test_created_file_permissions(self):
        with tempfile.TemporaryDirectory() as download_dir, \
             patch("xpra.platform.paths.get_download_dir", return_value=download_dir):
            filename, fd = safe_open_download_file("private.txt", "")
            os.close(fd)
            self.assertEqual(stat.S_IMODE(os.stat(filename).st_mode), 0o644)


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
        state = SendChunkState(
            start=0.0, send_id="", filesize=5,
            data=b"hello", chunk_size=65536, timer=0, chunk=0,
        )
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
        # parse_printer_caps reads the "file" namespace in legacy mode and "printer" otherwise.
        # The flag is looked up at call time from the file_transfer module globals, so patch it
        # there to exercise both modes in-process (the env var is only read once, at import time):
        for backwards_compatible in (True, False):
            with self.subTest(backwards_compatible=backwards_compatible), \
                    patch.object(file_transfer, "BACKWARDS_COMPATIBLE", backwards_compatible):
                caps_key = "file" if backwards_compatible else "printer"
                fth = FileTransferHandler()
                fth.init_attributes()
                caps = typedict({caps_key: {"printing": True, "printing-ask": True}})
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
        fth.files_accepted["my-id"] = AcceptedData(False, False)
        ok, _, _ = fth.accept_data("my-id", "file", "f.txt", False, False)
        self.assertTrue(ok)
        # consumed on use
        self.assertNotIn("my-id", fth.files_accepted)
        fth.cleanup()

    def test_accept_data_pre_accepted_print_stays_print(self):
        fth = MinimalFTH()
        fth.files_accepted["my-id"] = AcceptedData(True, True)
        ok, printit, openit = fth.accept_data("my-id", "file", "f.txt", True, True)
        self.assertTrue(ok)
        self.assertTrue(printit)
        self.assertTrue(openit)
        self.assertNotIn("my-id", fth.files_accepted)
        fth.cleanup()

    def test_accept_data_request_metadata_match(self):
        fth = MinimalFTH()
        fth.record_data_request_acceptance("my-id", "file", "f.txt", "text/plain", 4,
                                           False, True, typedict({"printer": "p1"}))
        opts = typedict({"printer": "p1", "sha256": "0" * 64, "file-chunk-id": "chunk-id"})
        ok, printit, openit = fth.accept_data("my-id", "file", "f.txt", False, False,
                                              "text/plain", 4, opts)
        self.assertTrue(ok)
        self.assertFalse(printit)
        self.assertTrue(openit)
        self.assertNotIn("my-id", fth.data_send_requests)
        fth.cleanup()

    def test_accept_data_request_metadata_mismatch(self):
        cases = (
            ("datatype", ("url", "f.txt", "text/plain", 4, typedict({"printer": "p1"}))),
            ("filename", ("file", "other.txt", "text/plain", 4, typedict({"printer": "p1"}))),
            ("mimetype", ("file", "f.txt", "application/octet-stream", 4, typedict({"printer": "p1"}))),
            ("filesize", ("file", "f.txt", "text/plain", 5, typedict({"printer": "p1"}))),
            ("options", ("file", "f.txt", "text/plain", 4, typedict({"printer": "p2"}))),
        )
        for name, args in cases:
            with self.subTest(name):
                fth = MinimalFTH()
                fth.record_data_request_acceptance("my-id", "file", "f.txt", "text/plain", 4,
                                                   False, True, typedict({"printer": "p1"}))
                self.assertEqual(fth.accept_data("my-id", args[0], args[1], False, False,
                                                 args[2], args[3], args[4]), (False, False, False))
                self.assertNotIn("my-id", fth.data_send_requests)
                fth.cleanup()

    def test_accepted_data_request_only_compares_approval_options(self):
        request = AcceptedDataRequest("file", "f.txt", "text/plain", 4, False, False, {"printer": "p1"})
        self.assertTrue(request.matches("file", "f.txt", "text/plain", 4, {
            "printer": "p1",
            "sha256": "0" * 64,
            "file-chunk-id": "chunk-id",
            "future-transfer-option": "ignored",
        }))

    def test_accept_data_openit_disabled(self):
        fth = MinimalFTH()
        fth.file_transfer = True
        fth.open_files = False
        ok, _, openit = fth.accept_data("sid", "file", "f.txt", False, True)
        self.assertTrue(ok)
        self.assertFalse(openit)
        fth.cleanup()

    def test_accept_data_authorization_matrix(self):
        cases = (
            ("file enabled", {"file_transfer": True}, "file", False, False, (True, False, False)),
            ("file disabled", {}, "file", False, False, (False, False, False)),
            ("file ask", {"file_transfer": True, "file_transfer_ask": True},
             "file", False, False, (False, False, False)),
            ("print enabled", {"printing": True}, "file", True, True, (True, True, False)),
            ("print disabled", {"file_transfer": True}, "file", True, False, (False, False, False)),
            ("print ask", {"printing": True, "printing_ask": True},
             "file", True, False, (False, False, False)),
            ("open enabled", {"file_transfer": True, "open_files": True},
             "file", False, True, (True, False, True)),
            ("open disabled", {"file_transfer": True}, "file", False, True, (True, False, False)),
            ("open ask", {"file_transfer": True, "open_files": True, "open_files_ask": True},
             "file", False, True, (True, False, False)),
            ("url enabled", {"open_url": True}, "url", False, True, (True, False, True)),
            ("url disabled", {}, "url", False, True, (False, False, False)),
            ("url ask", {"open_url": True, "open_url_ask": True},
             "url", False, True, (False, False, False)),
            ("unknown type", {"file_transfer": True}, "other", False, False, (False, False, False)),
        )
        for name, attributes, dtype, printit, openit, expected in cases:
            with self.subTest(name):
                fth = MinimalFTH()
                for key, value in attributes.items():
                    setattr(fth, key, value)
                self.assertEqual(fth.accept_data("sid", dtype, "item", printit, openit), expected)
                fth.cleanup()

    def test_process_open_url_authorization_matrix(self):
        cases = (
            ("disabled", False, False, False),
            ("enabled", True, False, True),
            ("ask without approval", True, True, False),
        )
        for name, enabled, ask, expected_open in cases:
            with self.subTest(name):
                fth = MinimalFTH()
                fth.open_url = enabled
                fth.open_url_ask = ask
                with patch.object(fth, "_open_url") as open_url:
                    fth._process_open_url(Packet("open-url", "https://example.com", "sid"))
                self.assertEqual(open_url.called, expected_open)
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
        self.assertTrue(any(p[0] == "file-send" for p in fth.sent))
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
        # the request is matched on the send-id we generated, not the filename:
        fth.files_requested["sid"] = RequestedFile("f.txt", True)
        opts = typedict({"request-file": ("f.txt", True)})
        fth.do_process_file_data_request("file", "sid", "f.txt", 100, False, True, opts)
        self.assertTrue(any(p[0] == "file-data-response" and p[2] is True for p in fth.sent))
        fth.cleanup()

    def test_do_process_file_data_request_rejects_mismatched_basename(self):
        fth = MinimalFTH()
        fth.file_transfer = True
        fth.files_requested["sid"] = RequestedFile("f.txt", True)
        opts = typedict({"request-file": ("f.txt", True)})
        fth.do_process_file_data_request("file", "sid", "other.txt", 100, False, True, opts)
        self.assertFalse(any(p[0] == "file-data-response" and p[2] is True for p in fth.sent))
        self.assertIn("sid", fth.files_requested)
        fth.cleanup()

    def test_do_process_file_data_request_matches_basename_pattern(self):
        fth = MinimalFTH()
        fth.file_transfer = True
        fth.files_requested["sid"] = RequestedFile("${XPRA_SERVER_LOG}", True, "*.log")
        opts = typedict({"request-file": ("${XPRA_SERVER_LOG}", True)})
        fth.do_process_file_data_request("file", "sid", "/tmp/xpra-server.log", 100, False, True, opts)
        self.assertTrue(any(p[0] == "file-data-response" and p[2] is True for p in fth.sent))
        fth.cleanup()

    def test_do_process_file_data_request_unrequested_send_id(self):
        # a server cannot get auto-accepted by spoofing the request-file option
        # if the send-id does not match a request we actually made:
        fth = MinimalFTH()
        fth.file_transfer = True
        fth.files_requested["sid"] = RequestedFile("f.txt", True)
        opts = typedict({"request-file": ("f.txt", True)})
        fth.do_process_file_data_request("file", "other-sid", "f.txt", 100, False, True, opts)
        self.assertFalse(any(p[0] == "file-data-response" and p[2] is True for p in fth.sent))
        self.assertIn("sid", fth.files_requested)
        fth.cleanup()

    def test_do_process_file_data_request_mismatched_requested_file(self):
        fth = MinimalFTH()
        fth.file_transfer = True
        fth.files_requested["sid"] = RequestedFile("${XPRA_SERVER_LOG}", True)
        opts = typedict({"request-file": ("other-file", True)})
        fth.do_process_file_data_request("file", "sid", "f.txt", 100, False, True, opts)
        self.assertFalse(any(p[0] == "file-data-response" and p[2] is True for p in fth.sent))
        self.assertIn("sid", fth.files_requested)
        fth.cleanup()

    def test_do_process_file_data_request_preserves_print_request(self):
        fth = MinimalFTH()
        fth.files_requested["sid"] = RequestedFile("print-job.pdf", True)
        opts = typedict({"request-file": ("print-job.pdf", True)})
        fth.do_process_file_data_request("file", "sid", "print-job.pdf", 100, True, True, opts, "application/pdf")
        self.assertEqual(fth.data_send_requests["sid"], AcceptedDataRequest(
            "file", "print-job.pdf", "application/pdf", 100, True, True, {
                "request-file": ("print-job.pdf", True),
            },
        ))
        fth.cleanup()

    def test_requested_file_acceptance_is_metadata_bound(self):
        fth = MinimalFTH()
        fth.files_requested["sid"] = RequestedFile("server.log", False)
        opts = typedict({"request-file": ("server.log", False)})
        fth.do_process_file_data_request("file", "sid", "server.log", 100, False, True, opts, "text/plain")
        self.assertEqual(fth.accept_data("sid", "file", "other.log", False, False,
                                         "text/plain", 100, opts), (False, False, False))
        self.assertNotIn("sid", fth.data_send_requests)
        fth.cleanup()

    def test_data_request_authorization_matrix(self):
        cases = (
            ("file ask", {"file_transfer": True, "file_transfer_ask": True},
             "file", False, False, "ask"),
            ("file disabled", {}, "file", False, False, "deny"),
            ("unneeded file request", {"file_transfer": True}, "file", False, False, "deny"),
            ("print ask", {"printing": True, "printing_ask": True},
             "file", True, True, "ask"),
            ("print ask without transfers", {"printing": True, "printing_ask": True},
             "file", True, False, "ask"),
            ("print disabled", {"file_transfer": True}, "file", True, False, "deny"),
            ("open ask", {"file_transfer": True, "open_files": True, "open_files_ask": True},
             "file", False, True, "ask"),
            ("open disabled", {"file_transfer": True}, "file", False, True, "deny"),
            ("url ask", {"open_url": True, "open_url_ask": True},
             "url", False, True, "ask"),
            ("url disabled", {}, "url", False, True, "deny"),
        )
        for name, attributes, dtype, printit, openit, expected in cases:
            with self.subTest(name):
                fth = MinimalFTH()
                for key, value in attributes.items():
                    setattr(fth, key, value)
                with patch.object(fth, "ask_data_request") as ask:
                    fth.do_process_file_data_request(
                        dtype, "sid", "/path/item", 100, printit, openit, typedict(),
                    )
                self.assertEqual(ask.called, expected == "ask")
                denied = any(p[0] == "file-data-response" and p[2] is False for p in fth.sent)
                self.assertEqual(denied, expected == "deny")
                fth.cleanup()

    def test_default_ask_data_request_denies(self):
        fth = MinimalFTH()
        answers = []
        fth.ask_data_request(answers.append, "sid", "file", "item", 100, False, False)
        self.assertEqual(answers, [False])
        fth.cleanup()

# ---------------------------------------------------------------------------
# Helpers shared by packet-handler tests
# ---------------------------------------------------------------------------


class _FullHandler(FileTransferHandler):
    """Concrete handler with all abstract methods filled in for packet tests."""

    def __init__(self):
        self.init_attributes()
        self.file_transfer = True
        self.file_transfer_ask = False
        self.file_size_limit = 1024 ** 3
        self.printing = True
        self.printing_ask = False
        self.open_files = True
        self.open_files_ask = False
        self.open_url = True
        self.open_url_ask = False
        self.file_ask_timeout = 60
        self.file_chunks = 65536
        self.open_command = "xdg-open"
        self.remote_file_transfer = True
        self.remote_file_transfer_ask = False
        self.remote_file_size_limit = 1024 ** 3
        self.remote_file_chunks = 65536
        self.remote_printing = True
        self.remote_printing_ask = False
        self.remote_open_files = True
        self.remote_open_files_ask = False
        self.remote_open_url = True
        self.remote_open_url_ask = False
        self.remote_file_ask_timeout = 60
        self.sent = []
        self.progress = []

    def send(self, packet_type, *args):
        self.sent.append((packet_type,) + args)

    def compressed_wrapper(self, datatype, data, level=5):
        from xpra.net.compression import Compressed
        return Compressed(datatype, data)

    def transfer_progress_update(self, send=True, transfer_id="", elapsed=0.0,
                                 position=0, total=0, error=None):
        self.progress.append((send, transfer_id, position, total, error))


def _make_receive_state(h, chunk_id="cid1", filesize=100):
    fd_val, path = tempfile.mkstemp()
    state = ReceiveChunkState(
        start=monotonic(), fd=fd_val, filename=path, mimetype="raw",
        printit=False, openit=False, filesize=filesize,
        options=typedict({"sha256": ""}), digest=None, written=0,
        cancelled=False, send_id="sid1", timer=0, chunk=0,
    )
    h.receive_chunks_in_progress[chunk_id] = state
    return state, path


def _make_send_state(h, chunk_id="scid1", data=b"0123456789" * 10):
    from xpra.net.file_transfer import SendChunkState
    state = SendChunkState(
        start=monotonic(), data=data, chunk_size=10, timer=0, chunk=0,
        send_id="sid1", filesize=len(data),
    )
    h.send_chunks_in_progress[chunk_id] = state
    return state


# ---------------------------------------------------------------------------
# _process_file_send_chunk
# ---------------------------------------------------------------------------

class TestProcessFileSendChunk(unittest.TestCase):

    def _pkt(self, chunk_id="cid1", chunk=1, data=b"hello", has_more=False):
        return Packet("file-send-chunk", chunk_id, chunk, data, has_more)

    def test_unknown_chunk_id_cancels(self):
        h = _FullHandler()
        pkt = self._pkt(chunk_id="no-such-id")
        with patch("xpra.net.file_transfer.GLib"), \
             patch.object(h, "cancel_file") as m:
            h._process_file_send_chunk(pkt)
            m.assert_called()

    def test_cancelled_state_ignored(self):
        h = _FullHandler()
        state, path = _make_receive_state(h)
        state.cancelled = True
        pkt = self._pkt(chunk=1)
        try:
            with patch("xpra.net.file_transfer.GLib"):
                h._process_file_send_chunk(pkt)
            assert not any(p[0] == "file-ack-chunk" for p in h.sent)
        finally:
            try:
                os.close(state.fd)
                os.unlink(path)
            except OSError:
                pass

    def test_chunk_mismatch_cancels(self):
        h = _FullHandler()
        state, path = _make_receive_state(h)
        state.chunk = 5  # next expected would be 6
        pkt = self._pkt(chunk=3)
        try:
            with patch("xpra.net.file_transfer.GLib"), \
                 patch.object(h, "cancel_file") as m:
                h._process_file_send_chunk(pkt)
                m.assert_called()
        finally:
            try:
                os.close(state.fd)
                os.unlink(path)
            except OSError:
                pass

    def test_overflow_cancels(self):
        h = _FullHandler()
        state, path = _make_receive_state(h, filesize=5)
        state.chunk = 0
        pkt = self._pkt(chunk=1, data=b"x" * 100)
        try:
            with patch("xpra.net.file_transfer.GLib"), \
                 patch.object(h, "cancel_file") as m:
                h._process_file_send_chunk(pkt)
                m.assert_called()
        finally:
            try:
                os.close(state.fd)
                os.unlink(path)
            except OSError:
                pass

    def test_has_more_acks_and_sets_timer(self):
        h = _FullHandler()
        state, path = _make_receive_state(h, filesize=1000)
        state.chunk = 0
        pkt = self._pkt(chunk=1, data=b"part", has_more=True)
        try:
            with patch("xpra.net.file_transfer.GLib") as mock_glib:
                mock_glib.timeout_add.return_value = 42
                mock_glib.source_remove.return_value = True
                h._process_file_send_chunk(pkt)
            assert any(p[0] == "file-ack-chunk" and p[2] is True for p in h.sent)
            assert state.timer == 42
        finally:
            try:
                os.close(state.fd)
                os.unlink(path)
            except OSError:
                pass

    def test_final_chunk_calls_process_downloaded(self):
        h = _FullHandler()
        data = b"complete"
        state, path = _make_receive_state(h, filesize=len(data))
        state.chunk = 0
        pkt = self._pkt(chunk=1, data=data, has_more=False)
        with patch.object(h, "process_downloaded_file") as m, \
             patch("xpra.net.file_transfer.GLib"):
            h._process_file_send_chunk(pkt)
            m.assert_called_once()
        try:
            os.unlink(path)
        except OSError:
            pass

    def test_digest_mismatch_cancels(self):
        import hashlib
        h = _FullHandler()
        data = b"content"
        state, path = _make_receive_state(h, filesize=len(data))
        state.chunk = 0
        state.digest = hashlib.sha256()
        state.options = typedict({"sha256": "0" * 64})  # intentionally wrong
        pkt = self._pkt(chunk=1, data=data, has_more=False)
        with patch.object(h, "cancel_file") as m, \
             patch("xpra.net.file_transfer.GLib"):
            h._process_file_send_chunk(pkt)
            m.assert_called()
        try:
            os.unlink(path)
        except OSError:
            pass


# ---------------------------------------------------------------------------
# _process_file_send
# ---------------------------------------------------------------------------

class TestProcessFileSend(unittest.TestCase):

    def _pkt(self, filename="f.txt", mimetype="", printit=False, openit=False,
             filesize=10, data=b"0123456789", options=None, send_id=""):
        opts = options or {}
        parts = [filename, mimetype, printit, openit, filesize, data, opts]
        if send_id:
            parts.append(send_id)
        return Packet("file-send", *parts)

    def test_zero_filesize_rejected(self):
        h = _FullHandler()
        pkt = self._pkt(filesize=0, data=b"")
        with patch("xpra.net.file_transfer.GLib"):
            h._process_file_send(pkt)
        assert not any(p[0] == "file-ack-chunk" for p in h.sent)

    def test_chunked_zero_filesize_rejected_without_name_error(self):
        h = _FullHandler()
        pkt = self._pkt(filesize=0, data=b"", options={"file-chunk-id": "cid1"})
        with patch("xpra.net.file_transfer.GLib"):
            h._process_file_send(pkt)
        self.assertIn(("file-ack-chunk", "cid1", False, "invalid file size 0 for 'f.txt'", 0), h.sent)

    def test_too_large_rejected(self):
        h = _FullHandler()
        h.file_size_limit = 5
        pkt = self._pkt(filesize=100, data=b"x" * 100)
        with patch("xpra.net.file_transfer.GLib"):
            h._process_file_send(pkt)

    def test_print_rejected_when_printing_disabled(self):
        h = _FullHandler()
        h.printing = False
        h.file_transfer = False
        pkt = self._pkt(printit=True)
        with patch("xpra.net.file_transfer.safe_open_download_file") as safe_open:
            h._process_file_send(pkt)
        safe_open.assert_not_called()

    def test_print_accepted_without_file_transfer(self):
        h = _FullHandler()
        h.printing = True
        h.file_transfer = False
        pkt = self._pkt(printit=True)
        tmp_fd, tmp_path = tempfile.mkstemp()
        with patch("xpra.net.file_transfer.safe_open_download_file",
                   return_value=(tmp_path, tmp_fd)), \
             patch.object(h, "process_downloaded_file") as processed:
            h._process_file_send(pkt)
        processed.assert_called_once()
        self.assertTrue(processed.call_args.args[2])
        os.unlink(tmp_path)

    def test_non_chunked_calls_process_downloaded(self):
        h = _FullHandler()
        data = b"hello world"
        pkt = self._pkt(filename="hello.txt", filesize=len(data), data=data)
        tmp_fd, tmp_path = tempfile.mkstemp()
        with patch("xpra.net.file_transfer.safe_open_download_file",
                   return_value=(tmp_path, tmp_fd)), \
             patch.object(h, "process_downloaded_file") as m, \
             patch("xpra.net.file_transfer.GLib"):
            h._process_file_send(pkt)
            m.assert_called_once()
        try:
            os.unlink(tmp_path)
        except OSError:
            pass

    def test_chunked_creates_receive_state(self):
        h = _FullHandler()
        pkt = self._pkt(filename="big.bin", filesize=200, data=b"",
                        options={"file-chunk-id": "cid99"})
        tmp_fd, tmp_path = tempfile.mkstemp()
        with patch("xpra.net.file_transfer.safe_open_download_file",
                   return_value=(tmp_path, tmp_fd)), \
             patch("xpra.net.file_transfer.GLib") as mock_glib:
            mock_glib.timeout_add.return_value = 1
            h._process_file_send(pkt)
        assert "cid99" in h.receive_chunks_in_progress
        h.receive_chunks_in_progress.clear()
        try:
            os.close(tmp_fd)
        except OSError:
            pass
        try:
            os.unlink(tmp_path)
        except OSError:
            pass

    def test_preaccepted_file_size_mismatch_rejected(self):
        h = _FullHandler()
        h.file_transfer_ask = True
        h.record_data_request_acceptance("sid", "file", "f.txt", "text/plain", 4, False, False, typedict())
        pkt = self._pkt(filename="f.txt", mimetype="text/plain", filesize=5, data=b"12345", send_id="sid")
        with patch("xpra.net.file_transfer.safe_open_download_file") as safe_open:
            h._process_file_send(pkt)
        safe_open.assert_not_called()
        self.assertNotIn("sid", h.data_send_requests)

    def test_preaccepted_chunked_file_mismatch_rejected_without_name_error(self):
        h = _FullHandler()
        h.file_transfer_ask = True
        h.record_data_request_acceptance("sid", "file", "f.txt", "text/plain", 4, False, False, typedict())
        pkt = self._pkt(filename="f.txt", mimetype="text/plain", filesize=5, data=b"",
                        options={"file-chunk-id": "cid1"}, send_id="sid")
        h._process_file_send(pkt)
        self.assertIn(("file-ack-chunk", "cid1", False, "transfer rejected for file 'f.txt'", 0), h.sent)
        self.assertNotIn("sid", h.data_send_requests)


# ---------------------------------------------------------------------------
# process_downloaded_file
# ---------------------------------------------------------------------------

class TestProcessDownloadedFile(unittest.TestCase):

    def test_request_file_callback_called(self):
        h = _FullHandler()
        called = []
        h.files_requested["sid"] = RequestedFile("${XPRA_SERVER_LOG}", False, "*.log")
        h.file_request_callback["sid"] = lambda fn, sz: called.append((fn, sz))
        with patch("xpra.net.file_transfer.GLib"):
            opts = typedict({"request-file": ("${XPRA_SERVER_LOG}", False)})
            h.process_downloaded_file("/tmp/server.log", "raw", False, False, 100, opts, "sid")
        assert called

    def test_request_file_callback_ignores_unmatched_send_id(self):
        # the callback is keyed on the send-id we generated: a server cannot
        # bypass it (and reach the open/print path) by spoofing the request-file
        # option in the file-send packet with a different/absent send-id:
        h = _FullHandler()
        callback = MagicMock()
        h.files_requested["sid"] = RequestedFile("${XPRA_SERVER_LOG}", True, "*.log")
        h.file_request_callback["sid"] = callback
        opts = typedict({"request-file": ("${XPRA_SERVER_LOG}", True)})
        with patch("xpra.net.file_transfer.start_thread") as start:
            h.process_downloaded_file("/tmp/server.log", "raw", False, True, 100, opts, "other-sid")
        callback.assert_not_called()
        self.assertIn("sid", h.file_request_callback)
        start.assert_called_once()

    def test_request_file_callback_is_one_shot(self):
        h = _FullHandler()
        callback = MagicMock()
        h.files_requested["sid"] = RequestedFile("${XPRA_SERVER_LOG}", False, "*.log")
        h.file_request_callback["sid"] = callback
        with patch("xpra.net.file_transfer.start_thread") as start:
            opts = typedict({"request-file": ("${XPRA_SERVER_LOG}", False)})
            h.process_downloaded_file("/tmp/first.log", "raw", False, False, 10, opts, "sid")
            h.process_downloaded_file("/tmp/second.log", "raw", False, False, 20, opts, "sid")
        callback.assert_called_once_with("/tmp/first.log", 10)
        self.assertNotIn("sid", h.file_request_callback)
        start.assert_not_called()

    def test_request_file_callback_failure_is_isolated(self):
        h = _FullHandler()
        callback = MagicMock(side_effect=RuntimeError("callback failed"))
        h.files_requested["sid"] = RequestedFile("${XPRA_SERVER_LOG}", False, "*.log")
        h.file_request_callback["sid"] = callback
        with patch("xpra.net.file_transfer.filelog") as filelog:
            opts = typedict({"request-file": ("${XPRA_SERVER_LOG}", False)})
            h.process_downloaded_file("/tmp/file.log", "raw", False, False, 10, opts, "sid")
        callback.assert_called_once_with("/tmp/file.log", 10)
        self.assertNotIn("sid", h.file_request_callback)
        self.assertTrue(filelog.error.called)

    def test_request_file_callback_rejects_mismatched_request_file(self):
        h = _FullHandler()
        callback = MagicMock()
        h.files_requested["sid"] = RequestedFile("${XPRA_SERVER_LOG}", False, "*.log")
        h.file_request_callback["sid"] = callback
        opts = typedict({"request-file": ("other-file", False)})
        with patch("xpra.net.file_transfer.start_thread") as start:
            h.process_downloaded_file("/tmp/server.log", "raw", False, True, 100, opts, "sid")
        callback.assert_not_called()
        self.assertIn("sid", h.file_request_callback)
        self.assertIn("sid", h.files_requested)
        start.assert_called_once()

    def test_request_file_callback_rejects_mismatched_basename(self):
        h = _FullHandler()
        callback = MagicMock()
        h.files_requested["sid"] = RequestedFile("expected.txt", False)
        h.file_request_callback["sid"] = callback
        opts = typedict({"request-file": ("expected.txt", False)})
        with patch("xpra.net.file_transfer.start_thread") as start:
            h.process_downloaded_file("/tmp/other.txt", "raw", False, True, 100, opts, "sid")
        callback.assert_not_called()
        self.assertIn("sid", h.file_request_callback)
        self.assertIn("sid", h.files_requested)
        start.assert_called_once()

    def test_no_action_no_thread(self):
        h = _FullHandler()
        with patch("xpra.net.file_transfer.start_thread") as m, \
             patch("xpra.net.file_transfer.GLib"):
            h.process_downloaded_file("/tmp/f.txt", "raw", False, False, 100, typedict())
            m.assert_not_called()

    def test_printit_starts_thread(self):
        h = _FullHandler()
        with patch("xpra.net.file_transfer.start_thread") as m, \
             patch("xpra.net.file_transfer.GLib"):
            h.process_downloaded_file("/tmp/f.txt", "raw", True, False, 100, typedict())
            m.assert_called_once()

    def test_process_thread_contract(self):
        h = _FullHandler()
        options = typedict({"key": "value"})
        with patch("xpra.net.file_transfer.start_thread") as start:
            h.process_downloaded_file("/tmp/f.txt", "raw", False, True, 100, options)
        start.assert_called_once_with(
            h.do_process_downloaded_file, "process-download", daemon=False,
            args=("/tmp/f.txt", "raw", False, True, 100, options),
        )

    def test_openit_starts_thread(self):
        h = _FullHandler()
        with patch("xpra.net.file_transfer.start_thread") as m, \
             patch("xpra.net.file_transfer.GLib"):
            h.process_downloaded_file("/tmp/f.txt", "raw", False, True, 100, typedict())
            m.assert_called_once()

    def test_do_process_print_takes_precedence(self):
        h = _FullHandler()
        with patch.object(h, "_print_file") as print_file, \
             patch.object(h, "_open_file") as open_file:
            h.do_process_downloaded_file("/tmp/f.txt", "raw", True, True, 100, typedict())
        print_file.assert_called_once()
        open_file.assert_not_called()

    def test_do_process_open_honors_current_setting(self):
        h = _FullHandler()
        for enabled in (False, True):
            with self.subTest(enabled=enabled), patch.object(h, "_open_file") as open_file:
                h.open_files = enabled
                h.do_process_downloaded_file("/tmp/f.txt", "raw", False, True, 100, typedict())
                self.assertEqual(open_file.called, enabled)


# ---------------------------------------------------------------------------
# _print_file
# ---------------------------------------------------------------------------

class TestPrintFile(unittest.TestCase):

    def test_no_printer_name_deletes_file(self):
        h = _FullHandler()
        tmp_fd, path = tempfile.mkstemp(suffix=".pdf")
        os.close(tmp_fd)
        with patch("xpra.net.file_transfer.GLib"), \
             patch("xpra.platform.printing.get_printers", return_value={"HP": {}}), \
             patch("xpra.platform.printing.print_files") as m_print, \
             patch("xpra.platform.printing.printing_finished", return_value=True):
            h._print_file(path, "application/pdf", typedict({}))
            m_print.assert_not_called()
        assert not os.path.exists(path)

    def test_printer_not_found_deletes_file(self):
        h = _FullHandler()
        tmp_fd, path = tempfile.mkstemp(suffix=".pdf")
        os.close(tmp_fd)
        with patch("xpra.net.file_transfer.GLib"), \
             patch("xpra.platform.printing.get_printers", return_value={}), \
             patch("xpra.platform.printing.print_files") as m_print, \
             patch("xpra.platform.printing.printing_finished", return_value=True):
            h._print_file(path, "application/pdf", typedict({"printer": "NoSuchPrinter"}))
            m_print.assert_not_called()
        assert not os.path.exists(path)

    def test_successful_print(self):
        h = _FullHandler()
        tmp_fd, path = tempfile.mkstemp(suffix=".pdf")
        os.close(tmp_fd)
        with patch("xpra.net.file_transfer.GLib") as mock_glib, \
             patch("xpra.platform.printing.get_printers", return_value={"MyPrinter": {}}), \
             patch("xpra.platform.printing.print_files", return_value=1) as m_print, \
             patch("xpra.platform.printing.printing_finished", return_value=True):
            mock_glib.timeout_add.return_value = 0
            h._print_file(path, "application/pdf",
                          typedict({"printer": "MyPrinter", "title": "My Doc"}))
            m_print.assert_called_once()

    def test_print_submission_exception_deletes_file(self):
        h = _FullHandler()
        fd, path = tempfile.mkstemp(suffix=".pdf")
        os.close(fd)
        with patch("xpra.platform.printing.get_printers", return_value={"Printer": {}}), \
             patch("xpra.platform.printing.print_files", side_effect=RuntimeError("print failed")), \
             patch("xpra.platform.printing.printing_finished"):
            h._print_file(path, "application/pdf", typedict({"printer": "Printer"}))
        self.assertFalse(os.path.exists(path))

    def test_invalid_print_job_deletes_file(self):
        h = _FullHandler()
        fd, path = tempfile.mkstemp(suffix=".pdf")
        os.close(fd)
        with patch("xpra.platform.printing.get_printers", return_value={"Printer": {}}), \
             patch("xpra.platform.printing.print_files", return_value=0), \
             patch("xpra.platform.printing.printing_finished"):
            h._print_file(path, "application/pdf", typedict({"printer": "Printer"}))
        self.assertFalse(os.path.exists(path))

    def test_pending_print_completes_from_timer(self):
        h = _FullHandler()
        fd, path = tempfile.mkstemp(suffix=".pdf")
        os.close(fd)
        with patch("xpra.net.file_transfer.GLib") as glib, \
             patch("xpra.platform.printing.get_printers", return_value={"Printer": {}}), \
             patch("xpra.platform.printing.print_files", return_value=1), \
             patch("xpra.platform.printing.printing_finished", side_effect=(False, True)):
            h._print_file(path, "application/pdf", typedict({"printer": "Printer"}))
            self.assertTrue(os.path.exists(path))
            callback = glib.timeout_add.call_args.args[1]
            self.assertFalse(callback())
        self.assertFalse(os.path.exists(path))

    def test_pending_print_times_out(self):
        from xpra.net.file_transfer import PRINT_JOB_TIMEOUT

        h = _FullHandler()
        fd, path = tempfile.mkstemp(suffix=".pdf")
        os.close(fd)
        with patch("xpra.net.file_transfer.GLib") as glib, \
             patch("xpra.net.file_transfer.monotonic", side_effect=(0, 0, PRINT_JOB_TIMEOUT + 1)), \
             patch("xpra.platform.printing.get_printers", return_value={"Printer": {}}), \
             patch("xpra.platform.printing.print_files", return_value=1), \
             patch("xpra.platform.printing.printing_finished", return_value=False):
            h._print_file(path, "application/pdf", typedict({"printer": "Printer"}))
            callback = glib.timeout_add.call_args.args[1]
            self.assertFalse(callback())
        self.assertFalse(os.path.exists(path))

    def test_print_status_exception_deletes_file(self):
        h = _FullHandler()
        fd, path = tempfile.mkstemp(suffix=".pdf")
        os.close(fd)
        with patch("xpra.platform.printing.get_printers", return_value={"Printer": {}}), \
             patch("xpra.platform.printing.print_files", return_value=1), \
             patch("xpra.platform.printing.printing_finished", side_effect=RuntimeError("status failed")):
            h._print_file(path, "application/pdf", typedict({"printer": "Printer"}))
        self.assertFalse(os.path.exists(path))

    def test_print_file_deletion_policy(self):
        h = _FullHandler()
        fd, path = tempfile.mkstemp(suffix=".pdf")
        os.close(fd)
        with patch("xpra.net.file_transfer.DELETE_PRINTER_FILE", False), \
             patch("xpra.platform.printing.get_printers", return_value={}), \
             patch("xpra.platform.printing.print_files"):
            h._print_file(path, "application/pdf", typedict())
        self.assertTrue(os.path.exists(path))
        os.unlink(path)

    def test_print_file_deletion_failure_is_logged(self):
        h = _FullHandler()
        fd, path = tempfile.mkstemp(suffix=".pdf")
        os.close(fd)
        with patch("xpra.platform.printing.get_printers", return_value={}), \
             patch("xpra.platform.printing.print_files"), \
             patch("xpra.net.file_transfer.os.unlink", side_effect=OSError("unlink failed")), \
             patch("xpra.net.file_transfer.printlog") as printlog:
            h._print_file(path, "application/pdf", typedict())
        self.assertTrue(any("delete" in str(call).lower() for call in printlog.error.call_args_list))
        os.unlink(path)


class TestOpenCommand(unittest.TestCase):

    def test_invalid_open_commands_are_rejected(self):
        for open_command in (None, "", "'unterminated"):
            with self.subTest(open_command=open_command):
                h = _FullHandler()
                h.open_command = open_command
                with patch("xpra.net.file_transfer.subprocess.Popen") as popen:
                    h.exec_open_command("/tmp/file.txt")
                popen.assert_not_called()

    def test_open_process_launch_failure(self):
        h = _FullHandler()
        h.open_command = "viewer --new-window"
        with patch("xpra.net.file_transfer.subprocess.Popen", side_effect=OSError("launch failed")) as popen, \
             patch("xpra.net.file_transfer.get_child_reaper") as child_reaper:
            h.exec_open_command("/tmp/file.txt")
        popen.assert_called_once()
        child_reaper.assert_not_called()

    def test_open_process_registration_and_failure_callback(self):
        from xpra.net.file_transfer import WIN32

        h = _FullHandler()
        h.open_command = "viewer --new-window"
        proc = MagicMock()
        proc.poll.return_value = 1
        reaper = MagicMock()
        with patch("xpra.net.file_transfer.subprocess.Popen", return_value=proc) as popen, \
             patch("xpra.net.file_transfer.get_child_reaper", return_value=reaper), \
             patch("xpra.net.file_transfer.filelog") as filelog:
            h.exec_open_command("/tmp/file.txt")
            command = ["viewer", "--new-window", "/tmp/file.txt"]
            popen.assert_called_once()
            self.assertEqual(popen.call_args.args[0], command)
            self.assertEqual(popen.call_args.kwargs["env"]["XPRA_XDG_OPEN"], "1")
            self.assertEqual(popen.call_args.kwargs["shell"], WIN32)
            registration = reaper.add_process.call_args.args
            self.assertEqual(registration[:5], (proc, "Open file /tmp/file.txt", command, True, True))
            callback = registration[5]
            callback()
        self.assertTrue(filelog.warn.called)

    def test_open_process_success_callback(self):
        h = _FullHandler()
        proc = MagicMock()
        proc.poll.return_value = 0
        reaper = MagicMock()
        with patch("xpra.net.file_transfer.subprocess.Popen", return_value=proc), \
             patch("xpra.net.file_transfer.get_child_reaper", return_value=reaper), \
             patch("xpra.net.file_transfer.filelog") as filelog:
            h.exec_open_command("/tmp/file.txt")
            reaper.add_process.call_args.args[-1]()
        filelog.warn.assert_not_called()

    def test_open_url_platform_paths(self):
        h = _FullHandler()
        with patch("xpra.net.file_transfer.POSIX", True), \
             patch.object(h, "exec_open_command") as open_command:
            h._open_url("https://example.com")
        open_command.assert_called_once_with("https://example.com")

        with patch("xpra.net.file_transfer.POSIX", False), \
             patch("webbrowser.open_new_tab") as open_tab:
            h._open_url("https://example.com")
        open_tab.assert_called_once_with("https://example.com")


# ---------------------------------------------------------------------------
# send_data_request
# ---------------------------------------------------------------------------

class TestSendDataRequest(unittest.TestCase):

    def test_returns_send_id(self):
        h = _FullHandler()
        with patch("xpra.net.file_transfer.GLib") as mock_glib:
            mock_glib.timeout_add.return_value = 1
            send_id = h.send_data_request("upload", "file", "/tmp/f.txt")
        assert send_id
        assert send_id in h.pending_send_data

    def test_sends_file_data_request_packet(self):
        from xpra.net.packet_type import FILE_DATA_REQUEST
        h = _FullHandler()
        with patch("xpra.net.file_transfer.GLib") as mock_glib:
            mock_glib.timeout_add.return_value = 1
            h.send_data_request("upload", "file", "/tmp/f.txt")
        assert any(p[0] == FILE_DATA_REQUEST for p in h.sent)

    def test_drops_when_too_many_pending(self):
        from xpra.net.file_transfer import MAX_CONCURRENT_FILES
        h = _FullHandler()
        for i in range(MAX_CONCURRENT_FILES):
            h.pending_send_data[f"id{i}"] = MagicMock()
        with patch("xpra.net.file_transfer.GLib"):
            send_id = h.send_data_request("upload", "file", "/tmp/x.txt")
        assert send_id == ""


# ---------------------------------------------------------------------------
# _process_file_data_response
# ---------------------------------------------------------------------------

class TestProcessFileDataResponse(unittest.TestCase):

    def _register(self, h, send_id, datatype="file", url="/tmp/f.txt", openit=False):
        h.pending_send_data[send_id] = SendPendingData(
            datatype=datatype, url=url, mimetype="", data=b"data",
            filesize=4, printit=False, openit=openit, options={},
        )

    def test_deny_removes_pending(self):
        h = _FullHandler()
        self._register(h, "s1")
        pkt = Packet("send-data-response", "s1", DENY)
        with patch("xpra.net.file_transfer.GLib"):
            h._process_file_data_response(pkt)
        assert "s1" not in h.pending_send_data

    def test_deny_completes_requested_file(self):
        h = _FullHandler()
        callback = MagicMock()
        h.files_requested["requested"] = RequestedFile("${XPRA_SERVER_LOG}", False, "*.log")
        h.file_request_callback["requested"] = callback
        pkt = Packet("file-data-response", "requested", DENY)
        h._process_file_data_response(pkt)
        callback.assert_not_called()
        self.assertNotIn("requested", h.files_requested)
        self.assertNotIn("requested", h.file_request_callback)

    def test_invalid_accept_removes_pending(self):
        h = _FullHandler()
        self._register(h, "s1b")
        pkt = Packet("send-data-response", "s1b", 99)
        with patch("xpra.net.file_transfer.GLib"):
            with self.assertRaises(ValueError):
                h._process_file_data_response(pkt)
        assert "s1b" not in h.pending_send_data

    def test_unknown_id_warns(self):
        h = _FullHandler()
        pkt = Packet("send-data-response", "no-such-id", ACCEPT)
        with patch("xpra.net.file_transfer.GLib"):
            h._process_file_data_response(pkt)   # must not raise

    def test_accept_file_calls_do_send_file(self):
        h = _FullHandler()
        self._register(h, "s2")
        pkt = Packet("send-data-response", "s2", ACCEPT)
        with patch.object(h, "do_send_file") as m, \
             patch("xpra.net.file_transfer.GLib"):
            h._process_file_data_response(pkt)
            m.assert_called_once()

    def test_accept_url_calls_do_send_open_url(self):
        h = _FullHandler()
        self._register(h, "s3", datatype="url", url="https://example.com")
        pkt = Packet("send-data-response", "s3", ACCEPT)
        with patch.object(h, "do_send_open_url") as m, \
             patch("xpra.net.file_transfer.GLib"):
            h._process_file_data_response(pkt)
            m.assert_called_once_with("https://example.com", "s3")

    def test_open_response_opens_locally(self):
        h = _FullHandler()
        self._register(h, "s4", datatype="file", url="/tmp/f.txt", openit=True)
        pkt = Packet("send-data-response", "s4", OPEN)
        with patch.object(h, "_open_file") as m, \
             patch("xpra.net.file_transfer.GLib") as glib:
            h._process_file_data_response(pkt)
            # the local open (which spawns a subprocess) is deferred to the main thread:
            glib.idle_add.assert_called_once_with(m, "/tmp/f.txt")


# ---------------------------------------------------------------------------
# _process_file_ack_chunk
# ---------------------------------------------------------------------------

class TestProcessFileAckChunk(unittest.TestCase):

    def test_state_false_cancels_sending(self):
        h = _FullHandler()
        _make_send_state(h, "sc1")
        pkt = Packet("file-ack-chunk", "sc1", False, "Cancelled", 0)
        with patch("xpra.net.file_transfer.GLib"), \
             patch.object(h, "cancel_sending") as m:
            h._process_file_ack_chunk(pkt)
            m.assert_called_once_with("sc1")

    def test_unknown_id_logs_error(self):
        h = _FullHandler()
        pkt = Packet("file-ack-chunk", "no-id", True, "", 0)
        with patch("xpra.net.file_transfer.GLib"):
            h._process_file_ack_chunk(pkt)  # must not raise

    def test_chunk_mismatch_cancels(self):
        h = _FullHandler()
        state = _make_send_state(h, "sc2")
        state.chunk = 3
        pkt = Packet("file-ack-chunk", "sc2", True, "", 5)
        with patch("xpra.net.file_transfer.GLib"), \
             patch.object(h, "cancel_sending") as m:
            h._process_file_ack_chunk(pkt)
            m.assert_called_once_with("sc2")

    def test_all_data_sent_cancels(self):
        h = _FullHandler()
        state = _make_send_state(h, "sc3", data=b"")
        state.chunk = 1
        pkt = Packet("file-ack-chunk", "sc3", True, "", 1)
        with patch("xpra.net.file_transfer.GLib"), \
             patch.object(h, "cancel_sending") as m:
            h._process_file_ack_chunk(pkt)
            m.assert_called_once_with("sc3")

    def test_sends_next_chunk(self):
        from xpra.net.packet_type import FILE_SEND_CHUNK
        h = _FullHandler()
        state = _make_send_state(h, "sc4", data=b"0123456789" * 5)
        state.chunk = 0
        pkt = Packet("file-ack-chunk", "sc4", True, "", 0)
        with patch("xpra.net.file_transfer.GLib") as mock_glib:
            mock_glib.timeout_add.return_value = 1
            mock_glib.source_remove.return_value = True
            h._process_file_ack_chunk(pkt)
        assert any(p[0] == FILE_SEND_CHUNK for p in h.sent)
        assert state.chunk == 1


class _LoopbackHandler(_FullHandler):

    def __init__(self, download_dir):
        super().__init__()
        self.download_dir = download_dir
        self.peer = None
        self.downloads = []
        self.held_packet_types = set()
        self.held_packets = []
        self.approve_requests = True
        self.corrupt_file_data = False

    def send(self, packet_type, *args):
        from xpra.net.compression import Compressed

        self.sent.append((packet_type,) + args)
        parts = [x.data if isinstance(x, Compressed) else x for x in args]
        if self.corrupt_file_data and packet_type == "file-send" and parts[5]:
            parts[5] = bytes(parts[5][:-1]) + bytes([parts[5][-1] ^ 0xFF])
            self.corrupt_file_data = False
        packet = Packet(packet_type, *parts)
        if packet_type in self.held_packet_types:
            self.held_packets.append(packet)
        else:
            self.peer.receive(packet)

    def receive(self, packet):
        handlers = {
            "file-send": self._process_file_send,
            "file-send-chunk": self._process_file_send_chunk,
            "file-ack-chunk": self._process_file_ack_chunk,
            "file-data-request": self._process_file_data_request,
            "file-data-response": self._process_file_data_response,
        }
        handlers[packet.get_type()](packet)

    def flush_held_packets(self):
        packets, self.held_packets = self.held_packets, []
        for packet in packets:
            self.peer.receive(packet)

    def ask_data_request(self, cb_answer, send_id, dtype, url, filesize, printit, openit,
                         mimetype="", options=None):
        if self.approve_requests:
            self.record_data_request_acceptance(send_id, dtype, url, mimetype, filesize,
                                                printit, openit, options)
        cb_answer(self.approve_requests)

    def process_downloaded_file(self, filename, mimetype, printit, openit, filesize, options, send_id=""):
        with open(filename, "rb") as f:
            self.downloads.append((os.path.basename(filename), f.read(), options))


class TestFileTransferLoopback(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.sender = _LoopbackHandler(self.tmpdir.name)
        self.receiver = _LoopbackHandler(self.tmpdir.name)
        self.sender.peer = self.receiver
        self.receiver.peer = self.sender
        self.glib_patcher = patch("xpra.net.file_transfer.GLib")
        self.glib = self.glib_patcher.start()
        self.glib.timeout_add.side_effect = range(1, 1000)

        def open_download_file(basefilename, _mimetype):
            path = os.path.join(self.tmpdir.name, f"received-{basename(basefilename)}")
            return path, os.open(path, os.O_CREAT | os.O_RDWR | os.O_EXCL, 0o600)

        self.safe_open_patcher = patch("xpra.net.file_transfer.safe_open_download_file",
                                       side_effect=open_download_file)
        self.safe_open_patcher.start()

    def tearDown(self):
        self.sender.cleanup()
        self.receiver.cleanup()
        self.safe_open_patcher.stop()
        self.glib_patcher.stop()
        self.tmpdir.cleanup()

    def test_non_chunked_transfer(self):
        self.sender.file_chunks = self.sender.remote_file_chunks = 0
        data = b"complete non-chunked payload"
        self.assertTrue(self.sender.send_file("payload.bin", "", data, len(data)))
        self.assertEqual(self.receiver.downloads[0][1], data)
        self.assertFalse(self.receiver.file_descriptors)

    def test_chunked_transfer(self):
        self.sender.file_chunks = self.sender.remote_file_chunks = 7
        data = b"chunked payload spanning several packets"
        self.assertTrue(self.sender.send_file("payload.bin", "", data, len(data)))
        self.assertEqual(self.receiver.downloads[0][1], data)
        self.assertFalse(self.sender.send_chunks_in_progress)
        self.assertFalse(self.receiver.receive_chunks_in_progress)
        self.assertGreater(len([p for p in self.sender.sent if p[0] == "file-send-chunk"]), 1)

    def test_unicode_filename_transfer(self):
        self.sender.file_chunks = self.sender.remote_file_chunks = 7
        filename = "r\u00e9sum\u00e9-\u65e5\u672c\u8a9e-\U0001f4c4.bin"
        data = b"unicode filename payload"
        self.assertTrue(self.sender.send_file(filename, "", data, len(data)))
        downloaded_name, downloaded_data, _options = self.receiver.downloads[0]
        self.assertEqual(downloaded_name, f"received-{filename}")
        self.assertEqual(downloaded_data, data)

    def test_approval_then_transfer(self):
        self.sender.remote_file_transfer_ask = True
        self.receiver.file_transfer_ask = True
        data = b"approved"
        self.assertTrue(self.sender.send_file("approved.bin", "", data, len(data)))
        self.assertEqual(self.receiver.downloads[0][1], data)
        self.assertFalse(self.sender.pending_send_data)
        self.assertFalse(self.sender.pending_send_data_timers)

    def test_denied_transfer(self):
        self.sender.remote_file_transfer_ask = True
        self.receiver.file_transfer_ask = True
        self.receiver.approve_requests = False
        self.assertTrue(self.sender.send_file("denied.bin", "", b"denied", 6))
        self.assertFalse(self.receiver.downloads)
        self.assertFalse(self.sender.pending_send_data)
        self.assertFalse(self.sender.pending_send_data_timers)

    def test_receiver_cancellation(self):
        self.sender.file_chunks = self.sender.remote_file_chunks = 4
        self.sender.held_packet_types.add("file-send-chunk")
        self.assertTrue(self.sender.send_file("cancel.bin", "", b"cancel this transfer", 20))
        chunk_id, state = next(iter(self.receiver.receive_chunks_in_progress.items()))
        path = state.filename
        self.receiver.cancel_download(state.send_id, "test cancellation")
        self.assertTrue(state.cancelled)
        self.assertNotIn(chunk_id, self.sender.send_chunks_in_progress)
        self.assertNotIn(state.fd, self.receiver.file_descriptors)
        self.assertFalse(os.path.exists(path))
        self.sender.flush_held_packets()
        self.assertFalse(self.receiver.downloads)

    def test_checksum_rejection(self):
        self.sender.file_chunks = self.sender.remote_file_chunks = 0
        self.sender.corrupt_file_data = True
        self.assertTrue(self.sender.send_file("corrupt.bin", "", b"checksum", 8))
        self.assertFalse(self.receiver.downloads)
        self.assertFalse(self.receiver.file_descriptors)
        self.assertFalse(os.path.exists(os.path.join(self.tmpdir.name, "received-corrupt.bin")))


class TestFileTransferFaults(unittest.TestCase):

    def test_partial_write_is_completed(self):
        h = _FullHandler()
        data = b"partial-write"
        fd, path = tempfile.mkstemp()
        os.close(fd)
        fd = os.open(path, os.O_RDWR | os.O_TRUNC)
        real_write = os.write
        calls = 0

        def partial_write(write_fd, write_data):
            nonlocal calls
            calls += 1
            if calls == 1:
                size = max(1, len(write_data) // 2)
                return real_write(write_fd, write_data[:size])
            return real_write(write_fd, write_data)

        packet = Packet("file-send", "partial.bin", "", False, False,
                        len(data), data, {})
        with patch("xpra.net.file_transfer.safe_open_download_file", return_value=(path, fd)), \
             patch("xpra.net.file_transfer.os.write", side_effect=partial_write), \
             patch.object(h, "process_downloaded_file") as processed:
            h._process_file_send(packet)
        with open(path, "rb") as f:
            self.assertEqual(f.read(), data)
        self.assertGreater(calls, 1)
        processed.assert_called_once()
        self.assertFalse(h.file_descriptors)
        os.unlink(path)

    def test_zero_length_write_cleans_up(self):
        h = _FullHandler()
        fd, path = tempfile.mkstemp()
        packet = Packet("file-send", "zero.bin", "", False, False, 4, b"data", {})
        with patch("xpra.net.file_transfer.safe_open_download_file", return_value=(path, fd)), \
             patch("xpra.net.file_transfer.os.write", return_value=0), \
             patch.object(h, "process_downloaded_file") as processed:
            h._process_file_send(packet)
        processed.assert_not_called()
        self.assertFalse(os.path.exists(path))
        self.assertFalse(h.file_descriptors)

    def test_chunk_write_failure_cancels_and_cleans_up(self):
        h = _FullHandler()
        state, path = _make_receive_state(h, filesize=4)
        h.file_descriptors.add(state.fd)
        packet = Packet("file-send-chunk", "cid1", 1, b"data", False)
        with patch("xpra.net.file_transfer.os.write", side_effect=OSError("disk full")), \
             patch("xpra.net.file_transfer.GLib"):
            h._process_file_send_chunk(packet)
        self.assertTrue(state.cancelled)
        self.assertFalse(os.path.exists(path))
        self.assertNotIn(state.fd, h.file_descriptors)
        self.assertTrue(any(p[0] == "file-ack-chunk" and p[2] is False for p in h.sent))

    def test_receive_timeout_cleans_up(self):
        h = _FullHandler()
        state, path = _make_receive_state(h, filesize=4)
        state.timer = 7
        h.file_descriptors.add(state.fd)
        with patch("xpra.net.file_transfer.GLib") as glib:
            h._check_chunk_receiving("cid1", 0)
        self.assertTrue(state.cancelled)
        self.assertEqual(state.timer, 0)
        self.assertFalse(os.path.exists(path))
        self.assertNotIn(state.fd, h.file_descriptors)
        glib.source_remove.assert_not_called()

    def test_duplicate_chunk_id_preserves_existing_transfer(self):
        h = _FullHandler()
        state, path = _make_receive_state(h)
        packet = Packet("file-send", "duplicate.bin", "", False, False, 100, b"",
                        {"file-chunk-id": "cid1"})
        with patch("xpra.net.file_transfer.safe_open_download_file") as safe_open:
            h._process_file_send(packet)
        safe_open.assert_not_called()
        self.assertIs(h.receive_chunks_in_progress["cid1"], state)
        self.assertTrue(any(p[0] == "file-ack-chunk" and p[2] is False for p in h.sent))
        os.close(state.fd)
        os.unlink(path)

    def test_truncated_final_chunk_cleans_up(self):
        h = _FullHandler()
        state, path = _make_receive_state(h, filesize=10)
        h.file_descriptors.add(state.fd)
        packet = Packet("file-send-chunk", "cid1", 1, b"short", False)
        with patch("xpra.net.file_transfer.GLib"):
            h._process_file_send_chunk(packet)
        self.assertTrue(state.cancelled)
        self.assertFalse(os.path.exists(path))
        self.assertNotIn(state.fd, h.file_descriptors)
        self.assertFalse(any(x[2] >= 0 for x in h.progress))


class TestMalformedFileTransferPackets(unittest.TestCase):

    def test_truncated_and_invalid_packet_fields(self):
        cases = (
            ("truncated file", "_process_file_send", Packet("file-send"), IndexError),
            ("truncated chunk", "_process_file_send_chunk", Packet("file-send-chunk", "cid"), IndexError),
            ("negative chunk", "_process_file_send_chunk",
             Packet("file-send-chunk", "cid", -1, b"data", False), ValueError),
            ("oversized ack chunk", "_process_file_ack_chunk",
             Packet("file-ack-chunk", "cid", True, "", 2**32), ValueError),
            ("invalid response", "_process_file_data_response",
             Packet("file-data-response", "sid", 128), ValueError),
            ("truncated request", "_process_file_data_request",
             Packet("file-data-request", "file"), IndexError),
            ("truncated URL", "_process_open_url", Packet("open-url"), IndexError),
            ("invalid options", "_process_file_send",
             Packet("file-send", "file", "", False, False, 4, b"data", b"options"), TypeError),
            ("invalid UTF-8 filename", "_process_file_send",
             Packet("file-send", b"\xff", "", False, False, 4, b"data", {}), UnicodeDecodeError),
        )
        for name, handler_name, packet, error_type in cases:
            with self.subTest(name):
                handler = _FullHandler()
                with self.assertRaises(error_type):
                    getattr(handler, handler_name)(packet)
                self.assertFalse(handler.file_descriptors)
                self.assertFalse(handler.receive_chunks_in_progress)
                self.assertFalse(handler.send_chunks_in_progress)

    def test_embedded_nul_filename_is_rejected_and_cleaned_up(self):
        handler = _FullHandler()
        packet = Packet("file-send", "invalid\0name", "", False, False, 4, b"data", {})
        with tempfile.TemporaryDirectory() as download_dir, \
             patch("xpra.platform.paths.get_download_dir", return_value=download_dir), \
             patch.object(handler, "process_downloaded_file") as processed:
            handler._process_file_send(packet)
            self.assertFalse(os.listdir(download_dir))
        processed.assert_not_called()
        self.assertFalse(handler.file_descriptors)


class TestReceiveChunkStateMachine(unittest.TestCase):

    def run_sequence(self, sequence, filesize):
        handler = _FullHandler()
        state, path = _make_receive_state(handler, filesize=filesize)
        handler.file_descriptors.add(state.fd)
        with patch("xpra.net.file_transfer.GLib") as glib, \
             patch.object(handler, "process_downloaded_file") as processed:
            glib.timeout_add.side_effect = range(1, 100)
            for chunk, data, has_more in sequence:
                handler._process_file_send_chunk(
                    Packet("file-send-chunk", "cid1", chunk, data, has_more),
                )
        return handler, state, path, processed

    def test_chunk_order_permutations(self):
        for order in itertools.permutations((1, 2, 3)):
            with self.subTest(order=order):
                sequence = tuple(
                    (chunk, bytes([chunk]), index < 2)
                    for index, chunk in enumerate(order)
                )
                handler, state, path, processed = self.run_sequence(sequence, 3)
                if order == (1, 2, 3):
                    processed.assert_called_once()
                    self.assertFalse(state.cancelled)
                    self.assertFalse(handler.receive_chunks_in_progress)
                    os.unlink(path)
                else:
                    processed.assert_not_called()
                    self.assertTrue(state.cancelled)
                    self.assertFalse(os.path.exists(path))
                self.assertFalse(handler.file_descriptors)

    def test_malformed_chunk_sequences(self):
        cases = (
            ("empty intermediate chunk", ((1, b"", True),), 4),
            ("more chunks after declared size", ((1, b"data", True),), 4),
            ("repeated chunk", ((1, b"ab", True), (1, b"cd", False)), 4),
            ("overflow", ((1, b"excess", False),), 4),
            ("truncated final chunk", ((1, b"abc", False),), 4),
        )
        for name, sequence, filesize in cases:
            with self.subTest(name):
                handler, state, path, processed = self.run_sequence(sequence, filesize)
                processed.assert_not_called()
                self.assertTrue(state.cancelled)
                self.assertFalse(os.path.exists(path))
                self.assertFalse(handler.file_descriptors)


class TestFileTransferTimersAndLimits(unittest.TestCase):

    def test_stale_receive_timeout_preserves_current_timer(self):
        handler = _FullHandler()
        state, path = _make_receive_state(handler)
        state.chunk = 2
        state.timer = 99
        with patch.object(handler, "cancel_file") as cancel:
            handler._check_chunk_receiving("cid1", 1)
        cancel.assert_not_called()
        self.assertEqual(state.timer, 99)
        os.close(state.fd)
        os.unlink(path)

    def test_stale_send_timeout_preserves_current_timer(self):
        handler = _FullHandler()
        state = _make_send_state(handler)
        state.chunk = 2
        state.timer = 99
        with patch.object(handler, "cancel_sending") as cancel:
            handler._check_chunk_sending("scid1", 1)
        cancel.assert_not_called()
        self.assertEqual(state.timer, 99)

    def test_current_send_timeout_cancels(self):
        handler = _FullHandler()
        state = _make_send_state(handler)
        state.chunk = 2
        state.timer = 99
        with patch.object(handler, "cancel_sending") as cancel:
            handler._check_chunk_sending("scid1", 2)
        cancel.assert_called_once_with("scid1")
        self.assertEqual(state.timer, 0)

    def test_receive_chunk_replaces_timer(self):
        handler = _FullHandler()
        state, path = _make_receive_state(handler, filesize=4)
        state.timer = 7
        with patch("xpra.net.file_transfer.GLib") as glib:
            glib.timeout_add.return_value = 8
            handler._process_file_send_chunk(
                Packet("file-send-chunk", "cid1", 1, b"ab", True),
            )
        glib.source_remove.assert_called_once_with(7)
        self.assertEqual(state.timer, 8)
        os.close(state.fd)
        os.unlink(path)

    def test_send_chunk_replaces_timer(self):
        handler = _FullHandler()
        state = _make_send_state(handler, data=b"abcd")
        state.chunk_size = 2
        state.timer = 7
        with patch("xpra.net.file_transfer.GLib") as glib:
            glib.timeout_add.return_value = 8
            handler._process_file_ack_chunk(Packet("file-ack-chunk", "scid1", True, "", 0))
        glib.source_remove.assert_called_once_with(7)
        self.assertEqual(state.timer, 8)
        self.assertEqual(state.chunk, 1)

    def test_cancellation_during_chunk_ack(self):
        handler = _FullHandler()
        state, path = _make_receive_state(handler, filesize=4)
        handler.file_descriptors.add(state.fd)

        def send(packet_type, *parts):
            if packet_type == "file-ack-chunk" and parts[1] is True:
                handler.cancel_file("cid1", "cancelled during acknowledgement", 1)

        with patch.object(handler, "send", side_effect=send), \
             patch("xpra.net.file_transfer.GLib") as glib:
            handler._process_file_send_chunk(
                Packet("file-send-chunk", "cid1", 1, b"ab", True),
            )
        self.assertTrue(state.cancelled)
        self.assertFalse(os.path.exists(path))
        self.assertNotIn(state.fd, handler.file_descriptors)
        glib.timeout_add.assert_called_once()

    def test_cleanup_closes_before_unlink_and_removes_all_timers(self):
        handler = _FullHandler()
        receive_state, path = _make_receive_state(handler)
        receive_state.timer = 7
        handler.file_descriptors.add(receive_state.fd)
        send_state = _make_send_state(handler)
        send_state.timer = 8
        handler.pending_send_data_timers["pending"] = 9
        real_unlink = os.unlink

        def checked_unlink(filename):
            with self.assertRaises(OSError):
                os.fstat(receive_state.fd)
            real_unlink(filename)

        with patch("xpra.net.file_transfer.GLib") as glib, \
             patch("xpra.net.file_transfer.os.unlink", side_effect=checked_unlink):
            handler.cleanup()
        self.assertCountEqual((x.args[0] for x in glib.source_remove.call_args_list), (7, 8, 9))
        self.assertFalse(os.path.exists(path))
        self.assertFalse(handler.file_descriptors)
        self.assertFalse(handler.receive_chunks_in_progress)
        self.assertFalse(handler.send_chunks_in_progress)

    def test_receive_concurrency_limit_cleans_new_file(self):
        from xpra.net.file_transfer import MAX_CONCURRENT_FILES

        handler = _FullHandler()
        handler.receive_chunks_in_progress.update(
            {f"active-{i}": MagicMock() for i in range(MAX_CONCURRENT_FILES)}
        )
        fd, path = tempfile.mkstemp()
        packet = Packet("file-send", "limited.bin", "", False, False, 4, b"",
                        {"file-chunk-id": "new-transfer"})
        with patch("xpra.net.file_transfer.safe_open_download_file", return_value=(path, fd)), \
             patch("xpra.net.file_transfer.GLib"):
            handler._process_file_send(packet)
        self.assertFalse(os.path.exists(path))
        self.assertNotIn(fd, handler.file_descriptors)
        self.assertTrue(any(p[0] == "file-ack-chunk" and p[2] is False for p in handler.sent))

    def test_send_concurrency_limit_rejects_new_transfer(self):
        from xpra.net.file_transfer import MAX_CONCURRENT_FILES

        handler = _FullHandler()
        handler.file_chunks = handler.remote_file_chunks = 2
        handler.send_chunks_in_progress.update(
            {f"active-{i}": MagicMock() for i in range(MAX_CONCURRENT_FILES)}
        )
        with patch("xpra.net.file_transfer.GLib"), self.assertRaises(RuntimeError):
            handler.do_send_file("limited.bin", "", b"data", 4)
        self.assertFalse(handler.sent)


class TestTransferProgressContracts(unittest.TestCase):

    def test_receive_progress_is_monotonic_and_terminal(self):
        handler = _FullHandler()
        state, path = _make_receive_state(handler, filesize=6)
        handler.file_descriptors.add(state.fd)
        with patch("xpra.net.file_transfer.GLib") as glib, \
             patch.object(handler, "process_downloaded_file") as processed:
            glib.timeout_add.return_value = 8
            handler._process_file_send_chunk(
                Packet("file-send-chunk", "cid1", 1, b"ab", True),
            )
            handler._process_file_send_chunk(
                Packet("file-send-chunk", "cid1", 2, b"cdef", False),
            )
        processed.assert_called_once()
        self.assertEqual([p[0] for p in handler.progress], [False, False])
        self.assertEqual([p[1] for p in handler.progress], ["sid1", "sid1"])
        self.assertEqual([p[2] for p in handler.progress], [2, 6])
        self.assertEqual([p[3] for p in handler.progress], [6, 6])
        self.assertEqual([p[4] for p in handler.progress], ["", ""])
        os.unlink(path)

    def test_receive_cancellation_has_one_terminal_error(self):
        handler = _FullHandler()
        state, path = _make_receive_state(handler, filesize=6)
        handler.file_descriptors.add(state.fd)
        with patch("xpra.net.file_transfer.GLib"):
            handler.cancel_download("sid1", "cancelled by user")
            handler.cancel_download("sid1", "cancelled again")
        self.assertEqual(len(handler.progress), 1)
        send, transfer_id, position, total, error = handler.progress[0]
        self.assertFalse(send)
        self.assertEqual(transfer_id, "sid1")
        self.assertEqual(position, -1)
        self.assertEqual(total, 6)
        self.assertEqual(error, "cancelled by user")
        self.assertFalse(os.path.exists(path))

    def test_non_chunked_send_reports_completion(self):
        handler = _FullHandler()
        handler.file_chunks = handler.remote_file_chunks = 0
        with patch("xpra.net.file_transfer.monotonic", side_effect=(10, 12)):
            handler.do_send_file("file.bin", "", b"data", 4, send_id="send-id")
        self.assertEqual(handler.progress, [(True, "send-id", 4, 4, None)])

    def test_chunked_send_reports_acknowledged_bytes(self):
        handler = _FullHandler()
        handler.file_chunks = handler.remote_file_chunks = 2
        with patch("xpra.net.file_transfer.GLib") as glib:
            glib.timeout_add.side_effect = range(1, 10)
            handler.do_send_file("file.bin", "", b"data", 4, send_id="send-id")
            chunk_id = next(iter(handler.send_chunks_in_progress))
            handler._process_file_ack_chunk(Packet("file-ack-chunk", chunk_id, True, "", 0))
            handler._process_file_ack_chunk(Packet("file-ack-chunk", chunk_id, True, "", 1))
            handler._process_file_ack_chunk(Packet("file-ack-chunk", chunk_id, True, "", 2))
        self.assertEqual([p[0] for p in handler.progress], [True, True, True])
        self.assertEqual([p[1] for p in handler.progress], ["send-id"] * 3)
        self.assertEqual([p[2] for p in handler.progress], [0, 2, 4])
        self.assertEqual([p[3] for p in handler.progress], [4, 4, 4])
        self.assertEqual([p[4] for p in handler.progress], [None, None, None])

    def test_remote_send_cancellation_reports_error(self):
        handler = _FullHandler()
        handler.file_chunks = handler.remote_file_chunks = 2
        with patch("xpra.net.file_transfer.GLib") as glib:
            glib.timeout_add.return_value = 1
            handler.do_send_file("file.bin", "", b"data", 4, send_id="send-id")
            chunk_id = next(iter(handler.send_chunks_in_progress))
            handler._process_file_ack_chunk(
                Packet("file-ack-chunk", chunk_id, False, "remote cancelled", 0),
            )
        self.assertEqual(len(handler.progress), 1)
        self.assertEqual(handler.progress[0][0:4], (True, "send-id", -1, 4))
        self.assertEqual(handler.progress[0][4], "remote cancelled")

    def test_send_timeout_reports_error(self):
        handler = _FullHandler()
        handler.file_chunks = handler.remote_file_chunks = 2
        with patch("xpra.net.file_transfer.GLib") as glib:
            glib.timeout_add.return_value = 1
            handler.do_send_file("file.bin", "", b"data", 4, send_id="send-id")
            chunk_id = next(iter(handler.send_chunks_in_progress))
            handler._check_chunk_sending(chunk_id, 0)
        self.assertEqual(len(handler.progress), 1)
        self.assertEqual(handler.progress[0][0:4], (True, "send-id", -1, 4))
        self.assertIn("timed out", handler.progress[0][4])

    def test_approval_timeout_reports_error(self):
        handler = _FullHandler()
        handler.pending_send_data["send-id"] = SendPendingData(
            datatype="file", url="file.bin", mimetype="", data=b"data",
            filesize=4, printit=False, openit=False, options={},
        )
        handler.send_data_ask_timeout("send-id")
        self.assertEqual(
            handler.progress,
            [(True, "send-id", -1, 4, "approval request timed out")],
        )


def main():
    unittest.main()


if __name__ == '__main__':
    main()
