#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2 or, at your option, any
# later version. See the file COPYING for details.

import unittest
from types import SimpleNamespace

from xpra.net.common import BACKWARDS_COMPATIBLE
from xpra.net.file_transfer import FileTransferAttributes
from xpra.server.source.file import FileConnection
from xpra.util.objects import typedict


class FileConnectionTest(unittest.TestCase):

    def test_is_needed(self):
        self.assertFalse(FileConnection.is_needed(typedict()))
        self.assertTrue(FileConnection.is_needed(typedict({"file": {}})))
        self.assertEqual(
            FileConnection.is_needed(typedict({"file-transfer": True})),
            BACKWARDS_COMPATIBLE,
        )
        self.assertFalse(FileConnection.is_needed(typedict({"file-transfer": False})))

    def test_init_from_copies_server_attributes(self):
        attributes = FileTransferAttributes()
        attributes.init_attributes(
            "ask", "20M", "no", "ask", "yes", "custom-open", can_ask=True,
        )
        server = SimpleNamespace(
            subsystems={"file": SimpleNamespace(file_transfer=attributes)},
        )
        connection = FileConnection()
        connection.init_from(None, server)
        for name in (
                "file_transfer", "file_transfer_ask", "file_size_limit", "file_chunks",
                "open_files", "open_files_ask", "open_url", "open_url_ask",
                "file_ask_timeout", "open_command"):
            with self.subTest(name=name):
                self.assertEqual(getattr(connection, name), getattr(attributes, name))

    def test_modern_capabilities_and_info(self):
        connection = FileConnection()
        connection.parse_client_caps(typedict({
            "file": {
                "enabled": True,
                "ask": True,
                "size-limit": 12345,
                "chunks": 4096,
                "open": True,
                "open-ask": True,
                "open-url": True,
                "open-url-ask": True,
                "ask-timeout": 60,
            },
        }))
        self.assertTrue(connection.remote_file_transfer)
        self.assertTrue(connection.remote_file_transfer_ask)
        self.assertEqual(connection.remote_file_size_limit, 12345)
        self.assertEqual(connection.remote_file_chunks, 4096)
        self.assertTrue(connection.remote_open_files)
        self.assertTrue(connection.remote_open_files_ask)
        self.assertTrue(connection.remote_open_url)
        self.assertTrue(connection.remote_open_url_ask)
        self.assertEqual(connection.remote_file_ask_timeout, 60)
        info = connection.get_info()
        self.assertIn("file-transfers", info)
        self.assertEqual(info["file-transfers"]["remote"]["file-size-limit"], 12345)

    @unittest.skipUnless(BACKWARDS_COMPATIBLE, "legacy capabilities disabled")
    def test_legacy_flat_capabilities(self):
        connection = FileConnection()
        connection.parse_client_caps(typedict({
            "file-transfer": True,
            "file-transfer-ask": True,
            "file-size-limit": 9876,
            "file-chunks": 2048,
            "open-files": True,
            "open-files-ask": True,
            "open-url": True,
            "open-url-ask": True,
            "file-ask-timeout": 120,
        }))
        self.assertTrue(connection.remote_file_transfer)
        self.assertTrue(connection.remote_file_transfer_ask)
        self.assertEqual(connection.remote_file_size_limit, 9876)
        self.assertEqual(connection.remote_file_chunks, 2048)
        self.assertTrue(connection.remote_open_files)
        self.assertTrue(connection.remote_open_files_ask)
        self.assertTrue(connection.remote_open_url)
        self.assertTrue(connection.remote_open_url_ask)
        self.assertEqual(connection.remote_file_ask_timeout, 120)


if __name__ == "__main__":
    unittest.main()
