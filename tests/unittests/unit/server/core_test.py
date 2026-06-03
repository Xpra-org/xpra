#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest
from types import SimpleNamespace
from unittest.mock import patch

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


def main():
    unittest.main()


if __name__ == "__main__":
    main()
