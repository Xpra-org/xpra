#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2 or, at your option, any
# later version. See the file COPYING for details.

from unittest.mock import patch

from xpra.net.common import BACKWARDS_COMPATIBLE
from xpra.net.file_transfer import FileTransferHandler
from xpra.util.objects import AdHocStruct, typedict
from unit.client.subsystem.clientmixintest_util import ClientMixinTest


class FileClientTest(ClientMixinTest):

    @staticmethod
    def make_opts():
        opts = AdHocStruct()
        opts.file_transfer = "yes"
        opts.file_size_limit = "10M"
        opts.printing = "no"
        opts.open_files = "yes"
        opts.open_url = "yes"
        opts.open_command = "xdg-open"
        return opts

    def test_modern_capabilities_and_packet_registration(self):
        from xpra.client.base.file import FileMixin

        caps = {
            "file": {
                "enabled": True,
                "ask": True,
                "size-limit": 12345,
                "chunks": 4096,
                "open": True,
                "open-url": True,
                "request-file": True,
            },
        }
        client = self._test_mixin_class(FileMixin, self.make_opts(), caps)
        self.assertTrue(client.remote_file_transfer)
        self.assertTrue(client.remote_file_transfer_ask)
        self.assertEqual(client.remote_file_size_limit, 12345)
        self.assertEqual(client.remote_file_chunks, 4096)
        self.assertTrue(client.remote_open_files)
        self.assertTrue(client.remote_open_url)
        self.assertTrue(client.remote_request_file)

        expected_packets = {
            "open-url", "file-send", "file-data-request", "file-data-response",
            "file-ack-chunk", "file-send-chunk",
        }
        self.assertEqual(set(self.packet_handlers), expected_packets)
        if BACKWARDS_COMPATIBLE:
            self.assertEqual(self.legacy_alias["send-file"], "file-send")
            self.assertEqual(self.legacy_alias["send-data-request"], "file-data-request")
            self.assertEqual(self.legacy_alias["send-data-response"], "file-data-response")
            self.assertEqual(self.legacy_alias["send-file-chunk"], "file-send-chunk")
            self.assertEqual(self.legacy_alias["ack-file-chunk"], "file-ack-chunk")

        local_caps = client.get_caps()
        self.assertTrue(local_caps["file"]["enabled"])
        self.assertEqual(local_caps["file"]["size-limit"], 10_000_000)
        info = client.get_info()
        self.assertIn("file-transfers", info)
        self.assertIn("remote", info["file-transfers"])

        client.send_request_file("server.log", True)
        self.assertEqual(self.packets[-1], ("file-request", "server.log", True))
        self.assertTrue(client.files_requested["server.log"])

    def test_request_file_capability_nesting_and_legacy_fallback(self):
        from xpra.client.base.file import FileMixin

        client = FileMixin()
        client.parse_server_capabilities(typedict({
            "request-file": True,
            "file": {"enabled": True, "request-file": False},
        }))
        self.assertFalse(client.remote_request_file)

        if not BACKWARDS_COMPATIBLE:
            return

        client.parse_server_capabilities(typedict({
            "file-transfer": True,
            "file-transfer-ask": True,
            "file-size-limit": 9876,
            "file-chunks": 2048,
            "open-files": True,
            "open-url": True,
            "request-file": True,
        }))
        self.assertTrue(client.remote_file_transfer)
        self.assertTrue(client.remote_file_transfer_ask)
        self.assertEqual(client.remote_file_size_limit, 9876)
        self.assertEqual(client.remote_file_chunks, 2048)
        self.assertTrue(client.remote_open_files)
        self.assertTrue(client.remote_open_url)
        self.assertTrue(client.remote_request_file)

    def test_cleanup_delegates_to_transfer_handler(self):
        from xpra.client.base.file import FileMixin

        client = FileMixin()
        with patch.object(FileTransferHandler, "cleanup", autospec=True) as cleanup:
            client.cleanup()
        cleanup.assert_called_once_with(client)


def main():
    import unittest
    unittest.main()


if __name__ == "__main__":
    main()
