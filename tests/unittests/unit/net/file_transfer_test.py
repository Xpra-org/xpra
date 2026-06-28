#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2020 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import tempfile
import unittest
from time import monotonic

from xpra.util import typedict
from xpra.net.file_transfer import (
    basename, safe_open_download_file,
    FileTransferAttributes, FileTransferHandler,
    ReceiveChunkState, URL_PREFIXES,
    )


class TestVersionUtilModule(unittest.TestCase):

    def test_basename(self):
        def t(s, e):
            r = basename(s)
            assert r==e, "expected '%s' but got '%s' for '%s'" % (r, e, s)
        t("hello", "hello")
        t("/path/to/foo", "foo")
        t("\\other\\path\\bar", "bar")


    def test_safe_open(self):
        filename, fd = safe_open_download_file("hello", "application/pdf")
        try:
            dupe_filename, dupe_fd = safe_open_download_file("hello", "application/pdf")
            assert dupe_filename!=filename
            try:
                os.close(dupe_fd)
            finally:
                os.unlink(dupe_filename)
            os.close(fd)
        finally:
            os.unlink(filename)


    def test_file_transfer_attributes(self):
        fta = FileTransferAttributes()
        assert fta.get_file_transfer_features()
        assert fta.get_info()

    def test_file_transfer_handler(self):
        fth = FileTransferHandler()
        fth.init_attributes()
        assert fth.get_open_env()
        caps = typedict()
        fth.parse_file_transfer_caps(caps)
        assert fth.get_info()
        fth.cleanup()


class MinimalFTH(FileTransferHandler):
    """A handler that records the packets it would send instead of transmitting them."""

    def __init__(self, file_transfer="yes", printing="no", open_files="no", open_url="yes"):
        super().__init__()
        self.init_attributes(file_transfer, "1G", printing, open_files, open_url)
        self.sent = []
        self.opened_urls = []

    def send(self, *parts):
        self.sent.append(parts)

    def _open_url(self, url):
        self.opened_urls.append(url)

    def transfer_progress_update(self, *_args, **_kwargs):
        pass

    def compressed_wrapper(self, _datatype, data, _level=5):
        return data

    def last_sent(self, packet_type):
        for p in reversed(self.sent):
            if p and p[0]==packet_type:
                return p
        return None


class TestDownloadPathSafety(unittest.TestCase):
    """safe_open_download_file must never escape the download directory."""

    def setUp(self):
        self.dd = tempfile.mkdtemp()
        import xpra.platform.paths as paths
        self._orig = paths.get_download_dir
        paths.get_download_dir = lambda: self.dd

    def tearDown(self):
        import xpra.platform.paths as paths
        paths.get_download_dir = self._orig

    def _open(self, name, mimetype="raw"):
        fn, fd = safe_open_download_file(name, mimetype)
        os.close(fd)
        return fn

    def test_dot_file_neutralized(self):
        fn = self._open(".bashrc")
        self.assertFalse(os.path.basename(fn).startswith("."))
        self.assertEqual(os.path.dirname(fn), self.dd)

    def test_all_dots_fallback(self):
        fn = self._open("...")
        self.assertTrue(os.path.basename(fn).startswith("download"))

    def test_path_traversal_confined(self):
        fn = self._open("../../etc/passwd")
        self.assertEqual(os.path.dirname(fn), self.dd)
        self.assertTrue(os.path.realpath(fn).startswith(os.path.realpath(self.dd)))

    def test_symlink_escape_skipped(self):
        outside = tempfile.mkdtemp()
        target = os.path.join(outside, "target")
        #a symlink in the download dir whose name matches the computed filename
        #(empty mimetype so that no extension is appended):
        os.symlink(target, os.path.join(self.dd, "evil"))
        fn = self._open("evil", "")
        self.assertNotEqual(os.path.basename(fn), "evil")
        self.assertTrue(os.path.realpath(fn).startswith(os.path.realpath(self.dd)))
        #nothing must have been created through the escaping symlink:
        self.assertFalse(os.path.exists(target))


class TestOpenURLRestriction(unittest.TestCase):
    """Only URLs matching the allowed prefixes may be opened."""

    def test_default_prefixes(self):
        self.assertIn("http://", URL_PREFIXES)
        self.assertIn("https://", URL_PREFIXES)

    def test_disallowed_scheme_rejected(self):
        h = MinimalFTH(open_url="yes")
        h._process_open_url(("open-url", "file:///etc/passwd", "sid"))
        self.assertEqual(h.opened_urls, [])

    def test_http_allowed(self):
        h = MinimalFTH(open_url="yes")
        h._process_open_url(("open-url", "http://example.com/", "sid"))
        self.assertEqual(h.opened_urls, ["http://example.com/"])

    def test_open_url_disabled(self):
        h = MinimalFTH(open_url="no")
        h._process_open_url(("open-url", "http://example.com/", "sid"))
        self.assertEqual(h.opened_urls, [])


class TestRequestFileSendId(unittest.TestCase):
    """A requested-file auto-accept must be bound to a client-generated send-id."""

    def test_send_request_file_uses_send_id(self):
        h = MinimalFTH()
        sid = h.send_request_file("f.txt", True, callback=lambda fn, sz: None)
        self.assertTrue(sid)
        self.assertIn(sid, h.files_requested)
        self.assertIn(sid, h.file_request_callback)
        pkt = h.last_sent("request-file")
        self.assertEqual(pkt[3], sid)

    def test_auto_accept_matches_send_id(self):
        h = MinimalFTH()
        sid = h.send_request_file("f.txt", True)
        h.do_process_send_data_request("file", sid, "f.txt", None, 100, False, True, typedict())
        resp = h.last_sent("send-data-response")
        self.assertTrue(resp[2])
        self.assertIn(sid, h.files_accepted)
        self.assertNotIn(sid, h.files_requested)

    def test_forged_request_file_option_rejected(self):
        #a server that did not get a matching send-id cannot have a file auto-accepted,
        #even by replaying a forged "request-file" option:
        h = MinimalFTH(file_transfer="no")
        h.do_process_send_data_request("file", "server-sid", "/etc/passwd", None, 100, False, True,
                                       typedict({"request-file": ("/etc/passwd", True)}))
        resp = h.last_sent("send-data-response")
        self.assertFalse(resp[2])

    def test_callback_keyed_on_send_id(self):
        h = MinimalFTH()
        called = []
        h.file_request_callback["sid"] = lambda fn, sz: called.append((fn, sz))
        h.process_downloaded_file("/tmp/f.txt", "raw", False, False, 100, typedict(), "sid")
        self.assertEqual(called, [("/tmp/f.txt", 100)])

    def test_callback_not_fired_for_other_send_id(self):
        h = MinimalFTH()
        called = []
        h.file_request_callback["realsid"] = lambda fn, sz: called.append((fn, sz))
        h.process_downloaded_file("/tmp/f.txt", "raw", False, False, 100, typedict(), "othersid")
        self.assertEqual(called, [])


class TestMalformedChunk(unittest.TestCase):
    """Malformed file chunks must be rejected through the normal cancellation path."""

    def _setup_chunk(self, h, filesize=10):
        fd, path = tempfile.mkstemp()
        cs = ReceiveChunkState(monotonic(), fd, path, "raw", False, False, filesize,
                               typedict(), None, 0, False, "sid", 0, 0)
        h.receive_chunks_in_progress["cid"] = cs
        return path

    def test_empty_chunk_rejected(self):
        h = MinimalFTH()
        path = self._setup_chunk(h)
        h._process_send_file_chunk(("send-file-chunk", "cid", 1, b"", False))
        ack = h.last_sent("ack-file-chunk")
        self.assertIsNotNone(ack)
        self.assertFalse(ack[2])  # transfer cancelled
        self.assertFalse(os.path.exists(path))

    def test_more_after_filesize_rejected(self):
        h = MinimalFTH()
        path = self._setup_chunk(h, filesize=5)
        h._process_send_file_chunk(("send-file-chunk", "cid", 1, b"12345", True))
        ack = h.last_sent("ack-file-chunk")
        self.assertIsNotNone(ack)
        self.assertFalse(ack[2])  # transfer cancelled
        self.assertFalse(os.path.exists(path))


def main():
    unittest.main()

if __name__ == '__main__':
    main()
