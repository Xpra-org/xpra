#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from xpra.server.mixins import child_command
from xpra.server.mixins.child_command import ChildCommandServer


class ChildCommandStartTest(unittest.TestCase):

    def test_count_watched_child_before_registration_callback(self):
        for ignore in (False, True):
            with self.subTest(ignore=ignore):
                server = ChildCommandServer.__new__(ChildCommandServer)
                server.exec_wrapper = []
                server.exec_cwd = None
                server.get_child_env = Mock(return_value={})
                server.get_full_child_command = Mock(return_value=["test-command"])
                server.exit_with_children = True
                server.children_count = 0
                server.children_started = []
                server.clean_quit = Mock()

                def register(*_args, **_kwargs):
                    # Registration may discover that all watched children exited.
                    server.reaper_exit_check()
                    return SimpleNamespace(dead=True)

                server.add_process = register
                with patch.object(child_command, "Popen") as popen, \
                        patch.object(child_command.GLib, "idle_add") as idle_add:
                    proc = server.start_command("test", ["test-command"], ignore=ignore)
                self.assertIs(proc, popen.return_value)
                self.assertEqual(server.children_count, int(not ignore))
                if ignore:
                    idle_add.assert_not_called()
                else:
                    idle_add.assert_called_once_with(server.clean_quit)


if __name__ == "__main__":
    unittest.main()
