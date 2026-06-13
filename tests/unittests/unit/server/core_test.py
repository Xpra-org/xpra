#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest
import sys
from types import SimpleNamespace
from unittest.mock import Mock, patch

from xpra.net.socket_util import SocketListener
from xpra.server.core import ServerCore


class TestServerCore(unittest.TestCase):

    def test_handle_ssh_connection_uses_display_name_api(self):
        server = ServerCore.__new__(ServerCore)
        display = SimpleNamespace(get_display_name=lambda: ":42")
        server.subsystems = {"display": display}
        conn = SimpleNamespace(socktype_wrapped="tcp")
        with patch("xpra.server.ssh.make_ssh_server_connection", return_value="ssh-conn") as make_ssh:
            result = server.handle_ssh_connection(conn, {})

        assert result == "ssh-conn"
        make_ssh.assert_called_once()
        assert make_ssh.call_args.kwargs["display_name"] == ":42"

    def test_start_listen_sockets_shows_vsock_endpoint(self):
        server = ServerCore.__new__(ServerCore)
        server.sockets = [
            SocketListener("vsock", object(), (0xffffffff, 10000), {}, lambda: None, lambda: None),
        ]
        server.unix_socket_paths = []
        mdns = SimpleNamespace(extra_info={})
        server.subsystems = {"mdns": mdns}
        vsock_mod = SimpleNamespace(
            CID_ANY=0xffffffff,
            CID_TYPES={0xffffffff: "ANY"},
            get_local_cid=lambda: 7,
        )

        with patch.dict(sys.modules, {"xpra.net.vsock.vsock": vsock_mod}):
            with patch("xpra.server.core.GLib.idle_add") as idle_add:
                log = SimpleNamespace(info=Mock())
                with patch("xpra.server.core.log", log):
                    server.start_listen_sockets()

        idle_add.assert_called_once_with(server.add_listen_socket, server.sockets[0])
        log.info.assert_any_call("listening on %s at %s:%s", "vsock", 7, 10000)
        log.info.assert_any_call("  %s://%s:%s", "vsock", 7, 10000)
        self.assertEqual(mdns.extra_info["vsock"], "7:10000")


def main():
    unittest.main()


if __name__ == "__main__":
    main()
