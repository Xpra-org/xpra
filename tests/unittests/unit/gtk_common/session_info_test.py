#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

"""Test that the session info helpers read the server details from the `remote-info` subsystem."""

import unittest
from types import SimpleNamespace


def make_client(last_info=None, **remote_info):
    subsystems = {
        "info": SimpleNamespace(last_info=last_info or {}),
    }
    if remote_info:
        subsystems["remote-info"] = SimpleNamespace(**remote_info)
    return SimpleNamespace(get_subsystem=subsystems.get)


class SessionInfoRemoteTest(unittest.TestCase):

    def test_remote_attr(self) -> None:
        from xpra.gtk.dialogs.session_info import remote_attr
        client = make_client(hostname="host")
        self.assertEqual(remote_attr(client, "hostname", ""), "host")
        self.assertEqual(remote_attr(client, "missing", "default"), "default")
        # no fallback to attributes of the client itself:
        client = SimpleNamespace(get_subsystem=lambda name: None, hostname="client")
        self.assertEqual(remote_attr(client, "hostname", ""), "")

    def test_from_remote_info(self) -> None:
        from xpra.gtk.dialogs import session_info
        client = make_client(platform="linux", version=(7, 0), branch="master", modifications=2,
                             build_date="2026-11-02", build_time="12:34")
        self.assertIn("Linux", session_info.get_server_platform_name(client))
        self.assertIn("7.0", session_info.get_server_version(client))
        self.assertEqual(session_info.get_server_revision_str(client), "M")
        self.assertIn("2026-11-02", session_info.get_server_builddate(client))

    def test_last_info_preferred(self) -> None:
        from xpra.gtk.dialogs import session_info
        last_info = {"server": {
            "platform": {"": "win32"},
            "build": {"date": "2025-01-01", "time": "00:00", "revision": 10, "local_modifications": 0},
        }}
        client = make_client(last_info, platform="linux", build_date="2026-11-02", build_time="12:34")
        self.assertIn("Windows", session_info.get_server_platform_name(client))
        self.assertIn("2025-01-01", session_info.get_server_builddate(client))
        self.assertIn("r10", session_info.get_server_revision_str(client))

    def test_no_remote_info(self) -> None:
        from xpra.gtk.dialogs import session_info
        client = make_client()
        self.assertEqual(session_info.get_server_revision_str(client), "")
        self.assertEqual(session_info.get_server_builddate(client), "")
        self.assertIn("unknown", session_info.get_server_version(client))


def main():
    try:
        import xpra.gtk.dialogs.session_info  # noqa: F401
    except ImportError as e:
        print(f"skipping session info test: {e}")
        return
    unittest.main()


if __name__ == '__main__':
    main()
