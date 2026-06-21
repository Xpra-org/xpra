#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2018 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from xpra.net.common import Packet
from xpra.net.control.common import ControlError
from xpra.util.objects import AdHocStruct
from xpra.os_util import POSIX
from unit.test_util import silence_info
from unit.server.subsystem.servermixintest_util import ServerMixinTest


class FileMixinTest(ServerMixinTest):

    def create_test_sockets(self):
        if not POSIX:
            return ()
        # socktype, socket, sockpath, cleanup_socket
        return [
            ("socket", None, "/fake/path", None)
        ]

    def test_fileprint(self):
        from xpra.server.subsystem import file as filesubsystem
        opts = AdHocStruct()
        opts.file_transfer = "yes"
        opts.file_size_limit = 10
        opts.printing = "yes"
        opts.open_files = "no"
        opts.open_url = "yes"
        opts.open_command = ""
        opts.lpadmin = "/usr/sbin/lpadmin"
        opts.lpinfo = "/usr/sbin/lpinfo"
        opts.add_printer_options = ""
        opts.postscript_printer = ""
        opts.pdf_printer = ""
        with silence_info(filesubsystem):
            self._test_mixin_class(filesubsystem.FileServer, opts)


class FileServerBehaviorTest(unittest.TestCase):

    class Owner:

        def __init__(self):
            self.subsystems = {}
            self._server_sources = {}
            self.source = None
            self.packet_handlers = {}
            self.legacy_aliases = {}

        def get_server_source(self, _proto):
            return self.source

        def add_packet_handler(self, packet_type, handler, _main_thread=False):
            self.packet_handlers[packet_type] = handler

        def add_legacy_alias(self, legacy_name, packet_type):
            self.legacy_aliases[legacy_name] = packet_type

    def setUp(self):
        from xpra.server.subsystem.file import FileServer

        self.owner = self.Owner()
        self.server = FileServer(self.owner)
        self.owner.subsystems["file"] = self.server
        self.server.file_transfer.init_attributes("yes", "1G", "yes", "yes", "yes", "")

    @staticmethod
    def make_source(uuid="client", file_size_limit=10**9, **attributes):
        source = SimpleNamespace(
            uuid=uuid,
            client_type="gtk",
            file_size_limit=file_size_limit,
            file_transfer=True,
            remote_file_transfer=True,
            printing=True,
            remote_printing=True,
            send_file=MagicMock(),
            send_open_url=MagicMock(return_value=True),
            notify_client=MagicMock(),
            _process_file_send=MagicMock(),
            _process_file_ack_chunk=MagicMock(),
            _process_file_send_chunk=MagicMock(),
            _process_file_data_request=MagicMock(),
            _process_file_data_response=MagicMock(),
        )
        for key, value in attributes.items():
            setattr(source, key, value)
        return source

    def test_packet_forwarding(self):
        source = self.make_source()
        self.owner.source = source
        packet = Packet("test")
        routes = (
            ("_process_file_send", "_process_file_send"),
            ("_process_file_ack_chunk", "_process_file_ack_chunk"),
            ("_process_file_send_chunk", "_process_file_send_chunk"),
            ("_process_file_data_request", "_process_file_data_request"),
            ("_process_file_data_response", "_process_file_data_response"),
        )
        for server_handler, source_handler in routes:
            with self.subTest(server_handler):
                getattr(self.server, server_handler)(object(), packet)
                getattr(source, source_handler).assert_called_once_with(packet)

        self.owner.source = None
        for server_handler, _source_handler in routes:
            with self.subTest(f"missing source: {server_handler}"):
                getattr(self.server, server_handler)(object(), packet)

    def test_packet_registration_and_legacy_aliases(self):
        self.server.init_packet_handlers()
        self.assertIn("file-request", self.owner.packet_handlers)
        self.assertEqual(self.owner.legacy_aliases["send-data-request"], "file-data-request")
        self.assertEqual(self.owner.legacy_aliases["send-data-response"], "file-data-response")

    def test_request_file_feature_is_namespaced(self):
        features = self.server.get_server_features(None)
        self.assertTrue(features["file"]["enabled"])
        self.assertTrue(features["file"]["request-file"])

    def test_request_file_success(self):
        source = self.make_source()
        self.owner.source = source
        with tempfile.NamedTemporaryFile() as f:
            f.write(b"requested data")
            f.flush()
            self.server._process_file_request(None, Packet("file-request", f.name, True))
        source.send_file.assert_called_once_with(
            f.name, "", b"requested data", 14, openit=True,
            options={"request-file": (f.name, True)},
        )

    def test_unicode_filename_request_and_control(self):
        source = self.make_source()
        self.owner.source = source
        self.owner._server_sources = {source.uuid: source}
        filename = "r\u00e9sum\u00e9-\u65e5\u672c\u8a9e-\U0001f4c4.txt"
        data = b"unicode filename"
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, filename)
            with open(path, "wb") as f:
                f.write(data)

            self.server._process_file_request(None, Packet("file-request", path, False))
            source.send_file.assert_called_once_with(
                path, "", data, len(data), openit=False,
                options={"request-file": (path, False)},
            )

            source.send_file.reset_mock()
            self.server.control_command_send_file(path, "false", source.uuid)
            source.send_file.assert_called_once_with(path, "", data, len(data), False, False)

    def test_request_file_missing_and_server_log_unset(self):
        source = self.make_source()
        self.owner.source = source
        with patch("xpra.server.subsystem.file.may_notify_client") as notify:
            self.server._process_file_request(None, Packet("file-request", "/missing/file", False))
            notify.assert_called_once()
            self.assertEqual(notify.call_args.args[2], "File not found")
            notify.reset_mock()
            with patch.dict(os.environ, {}, clear=True):
                self.server._process_file_request(
                    None, Packet("file-request", "${XPRA_SERVER_LOG}", False),
                )
            notify.assert_not_called()
        source.send_file.assert_not_called()

    def test_request_file_size_limits(self):
        source = self.make_source()
        self.owner.source = source
        with tempfile.NamedTemporaryFile() as f:
            f.write(b"too large")
            f.flush()
            for local_limit, remote_limit in ((3, 100), (100, 3)):
                with self.subTest(local_limit=local_limit, remote_limit=remote_limit), \
                     patch("xpra.server.subsystem.file.may_notify_client") as notify:
                    self.server.file_transfer.file_size_limit = local_limit
                    source.file_size_limit = remote_limit
                    self.server._process_file_request(None, Packet("file-request", f.name, False))
                    self.assertEqual(notify.call_args.args[2], "File too large")
        source.send_file.assert_not_called()

    def test_request_file_load_failure(self):
        source = self.make_source()
        self.owner.source = source
        with tempfile.NamedTemporaryFile() as f, \
             patch("xpra.server.subsystem.file.load_binary_file", return_value=b""), \
             patch("xpra.server.subsystem.file.may_notify_client") as notify:
            self.server._process_file_request(None, Packet("file-request", f.name, False))
        source.send_file.assert_not_called()
        self.assertEqual(notify.call_args.args[2], "File cannot be read")

    def test_control_open_url(self):
        accepted = self.make_source("accepted")
        rejected = self.make_source("rejected")
        rejected.send_open_url.return_value = False
        unsupported = SimpleNamespace(uuid="unsupported")
        self.owner._server_sources = {
            accepted.uuid: accepted,
            rejected.uuid: rejected,
            unsupported.uuid: unsupported,
        }
        self.assertEqual(self.server.control_command_open_url("https://example.com"), "url sent to 1 clients")
        accepted.send_open_url.assert_called_once_with("https://example.com")
        rejected.send_open_url.assert_called_once_with("https://example.com")

    def test_control_send_file_filters_clients(self):
        accepted = self.make_source("accepted")
        unsupported = self.make_source("unsupported", remote_file_transfer=False)
        too_small = self.make_source("too-small", file_size_limit=2)
        self.owner._server_sources = {x.uuid: x for x in (accepted, unsupported, too_small)}
        with tempfile.NamedTemporaryFile() as f:
            f.write(b"payload")
            f.flush()
            result = self.server.control_command_send_file(f.name, "false")
            accepted.send_file.assert_called_once_with(f.name, "", b"payload", 7, False, False)
        unsupported.send_file.assert_not_called()
        too_small.send_file.assert_not_called()
        self.assertIn("initiated", result)

    def test_control_print_preserves_job_metadata(self):
        source = self.make_source()
        self.owner._server_sources = {source.uuid: source}
        with tempfile.NamedTemporaryFile() as f:
            f.write(b"print me")
            f.flush()
            self.server.control_command_print(
                f.name, "Office", source.uuid, 0, "Report", "copies=2", "invalid", "=ignored",
            )
            source.send_file.assert_called_once_with(
                f.name, "", b"print me", 8, True, True,
                {"printer": "Office", "title": "Report", "copies": "2"},
            )

    def test_control_file_errors(self):
        source = self.make_source()
        self.owner._server_sources = {source.uuid: source}
        with self.assertRaises(ControlError):
            self.server.control_command_send_file("/missing/file")
        with tempfile.NamedTemporaryFile() as empty:
            with self.assertRaises(ControlError):
                self.server.control_command_send_file(empty.name)
        with tempfile.NamedTemporaryFile() as large:
            large.write(b"large")
            large.flush()
            self.server.file_transfer.file_size_limit = 2
            with self.assertRaises(ControlError):
                self.server.control_command_send_file(large.name)

        self.owner._server_sources = {}
        with self.assertRaises(ControlError):
            self.server.control_command_open_url("https://example.com")


def main():
    unittest.main()


if __name__ == '__main__':
    main()
