#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2020 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import unittest
import tempfile
from unittest.mock import MagicMock, patch
from time import monotonic

from xpra.net.common import Packet
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
            assert not any(p[0] == "ack-file-chunk" for p in h.sent)
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
            assert any(p[0] == "ack-file-chunk" and p[2] is True for p in h.sent)
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
        assert not any(p[0] == "ack-file-chunk" for p in h.sent)

    def test_too_large_rejected(self):
        h = _FullHandler()
        h.file_size_limit = 5
        pkt = self._pkt(filesize=100, data=b"x" * 100)
        with patch("xpra.net.file_transfer.GLib"):
            h._process_file_send(pkt)

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


# ---------------------------------------------------------------------------
# process_downloaded_file
# ---------------------------------------------------------------------------

class TestProcessDownloadedFile(unittest.TestCase):

    def test_request_file_callback_called(self):
        h = _FullHandler()
        called = []
        h.file_request_callback["myarg"] = lambda fn, sz: called.append((fn, sz))
        opts = typedict({"request-file": ("myarg", True)})
        with patch("xpra.net.file_transfer.GLib"):
            h.process_downloaded_file("/tmp/f.txt", "raw", False, False, 100, opts)
        assert called

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

    def test_openit_starts_thread(self):
        h = _FullHandler()
        with patch("xpra.net.file_transfer.start_thread") as m, \
             patch("xpra.net.file_transfer.GLib"):
            h.process_downloaded_file("/tmp/f.txt", "raw", False, True, 100, typedict())
            m.assert_called_once()


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
             patch("xpra.net.file_transfer.GLib"):
            h._process_file_data_response(pkt)
            m.assert_called_once_with("/tmp/f.txt")


# ---------------------------------------------------------------------------
# _process_file_ack_chunk
# ---------------------------------------------------------------------------

class TestProcessFileAckChunk(unittest.TestCase):

    def test_state_false_cancels_sending(self):
        h = _FullHandler()
        _make_send_state(h, "sc1")
        pkt = Packet("ack-file-chunk", "sc1", False, "Cancelled", 0)
        with patch("xpra.net.file_transfer.GLib"), \
             patch.object(h, "cancel_sending") as m:
            h._process_file_ack_chunk(pkt)
            m.assert_called_once_with("sc1")

    def test_unknown_id_logs_error(self):
        h = _FullHandler()
        pkt = Packet("ack-file-chunk", "no-id", True, "", 0)
        with patch("xpra.net.file_transfer.GLib"):
            h._process_file_ack_chunk(pkt)  # must not raise

    def test_chunk_mismatch_cancels(self):
        h = _FullHandler()
        state = _make_send_state(h, "sc2")
        state.chunk = 3
        pkt = Packet("ack-file-chunk", "sc2", True, "", 5)
        with patch("xpra.net.file_transfer.GLib"), \
             patch.object(h, "cancel_sending") as m:
            h._process_file_ack_chunk(pkt)
            m.assert_called_once_with("sc2")

    def test_all_data_sent_cancels(self):
        h = _FullHandler()
        state = _make_send_state(h, "sc3", data=b"")
        state.chunk = 1
        pkt = Packet("ack-file-chunk", "sc3", True, "", 1)
        with patch("xpra.net.file_transfer.GLib"), \
             patch.object(h, "cancel_sending") as m:
            h._process_file_ack_chunk(pkt)
            m.assert_called_once_with("sc3")

    def test_sends_next_chunk(self):
        from xpra.net.packet_type import FILE_SEND_CHUNK
        h = _FullHandler()
        state = _make_send_state(h, "sc4", data=b"0123456789" * 5)
        state.chunk = 0
        pkt = Packet("ack-file-chunk", "sc4", True, "", 0)
        with patch("xpra.net.file_transfer.GLib") as mock_glib:
            mock_glib.timeout_add.return_value = 1
            mock_glib.source_remove.return_value = True
            h._process_file_ack_chunk(pkt)
        assert any(p[0] == FILE_SEND_CHUNK for p in h.sent)
        assert state.chunk == 1


def main():
    unittest.main()


if __name__ == '__main__':
    main()
