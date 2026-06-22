#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import tempfile
import unittest
from time import time
from unittest.mock import patch

from xpra.server.subsystem.id import IDServer
from xpra.server.subsystem.info import InfoServer
from unit.server.subsystem.servermixintest_util import FakeServerBase


class FakeServer(FakeServerBase):
    session_type = "seamless"
    session_name = "test-session"

    def __init__(self):
        super().__init__()
        self.hello_request_handlers = {}
        self.start_time = time()
        self._html = False
        self.websocket_upgrade = False
        self._www_dir = ""
        self._http_headers_dirs = []
        self._default_packet_handlers = {}

    def get_socket_info(self) -> dict:
        return {}


class FakeSessionFiles:

    def __init__(self):
        self.files = {}

    def write_session_file(self, filename: str, contents) -> str:
        self.files[filename] = contents
        return filename


class TestIDInfo(unittest.TestCase):

    def make_server(self, uuid="test-uuid"):
        server = FakeServer()
        id_subsystem = IDServer(server)
        id_subsystem.uuid = uuid
        server.subsystems["id"] = id_subsystem
        return server

    def test_id_info_includes_uuid(self):
        server = self.make_server()

        info = server.subsystems["id"].get_info(None)

        self.assertEqual(info["uuid"], "test-uuid")

    def test_id_init_uuid_uses_session_file_uuid(self):
        server = FakeServer()
        id_subsystem = IDServer(server)
        server.subsystems["id"] = id_subsystem

        with tempfile.TemporaryDirectory() as tmpdir:
            with open(os.path.join(tmpdir, "server.uuid"), "w", encoding="latin1") as f:
                f.write("file-uuid\n")
            with patch.dict(os.environ, {"XPRA_SESSION_DIR": tmpdir}):
                id_subsystem.setup()
                self.assertEqual(id_subsystem.uuid, "file-uuid")

    def test_id_init_uuid_writes_session_file(self):
        server = FakeServer()
        session_files = FakeSessionFiles()
        server.subsystems["session-files"] = session_files
        id_subsystem = IDServer(server)
        server.subsystems["id"] = id_subsystem

        with patch.dict(os.environ, {}, clear=True), \
                patch("xpra.server.subsystem.id.get_hex_uuid", return_value="generated-uuid"):
            id_subsystem.setup()

        self.assertEqual(id_subsystem.uuid, "generated-uuid")
        self.assertEqual(session_files.files, {"server.uuid": "generated-uuid"})

    def test_id_init_uuid_generates_fallback_uuid(self):
        server = FakeServer()
        id_subsystem = IDServer(server)
        server.subsystems["id"] = id_subsystem

        with patch("xpra.server.subsystem.id.get_hex_uuid", return_value="generated-uuid"):
            id_subsystem.setup()
            self.assertEqual(id_subsystem.uuid, "generated-uuid")

    def test_threaded_info_includes_id_uuid(self):
        from xpra.server.core import ServerCore

        server = self.make_server()
        info_subsystem = InfoServer(server)
        server.subsystems["info"] = info_subsystem
        server.get_server_info = lambda full=False: ServerCore.get_server_info(server, full)

        with patch("xpra.server.core.FULL_INFO", 0):
            info = ServerCore.get_threaded_info(server, None)

        self.assertEqual(info["uuid"], "test-uuid")
        self.assertEqual(info["session-type"], "seamless")

    def test_server_session_id_info_delegates_to_id_subsystem(self):
        from xpra.server.core import ServerCore

        server = self.make_server()

        info = ServerCore.get_session_id_info(server)

        self.assertEqual(info["uuid"], "test-uuid")
        self.assertEqual(info["session-type"], "seamless")


def main():
    unittest.main()


if __name__ == "__main__":
    main()
