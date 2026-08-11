#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest
from io import StringIO
from unittest.mock import Mock, patch


class MenuProviderTest(unittest.TestCase):

    def test_force_reload_refreshes_sessions(self):
        from xpra.server import menu_provider
        provider = menu_provider.MenuProvider()
        with patch.object(menu_provider.MenuProvider, "get_menu_data") as get_menu_data, \
             patch.object(menu_provider.MenuProvider, "get_desktop_sessions") as get_desktop_sessions, \
             patch.object(menu_provider.MenuProvider, "clear_cache"), \
             patch.object(menu_provider, "install_menu_thread_seccomp", return_value=False), \
             patch.object(menu_provider, "start_thread", side_effect=lambda target, *_args: target()):
            provider.load_menu_data(True, cache=False)
        get_menu_data.assert_called_once_with(True)
        get_desktop_sessions.assert_called_once_with(True)

    def test_force_reload_reaches_platform_loader(self):
        from xpra.server.menu_provider import MenuProvider
        provider = MenuProvider()
        provider.menu_data = {"Old": {}}
        new_menu = {"New": {}}
        with patch("xpra.platform.menu_helper.load_menu", return_value=new_menu) as load_menu, \
             patch("xpra.server.menu_provider.add_work_item"):
            assert provider.get_menu_data(force_reload=True) == new_menu
        load_menu.assert_called_once_with(True)

    def test_modified_cache_forces_reload(self):
        from xpra.server import menu_provider

        class Process:
            pid = 1234
            returncode = 0
            stdout = StringIO("modified=2\n")

        process = Process()
        reaper = Mock()
        callbacks = []

        def add_process(_proc, _name, _cmd, **kwargs):
            callbacks.append(kwargs["callback"])

        reaper.add_process.side_effect = add_process
        provider = menu_provider.MenuProvider()
        with patch.object(menu_provider, "POSIX", True), \
             patch.object(menu_provider, "OSX", False), \
             patch.object(menu_provider, "Popen", return_value=process), \
             patch("xpra.platform.paths.get_xpra_command", return_value=["xpra"]), \
             patch("xpra.util.child_reaper.get_child_reaper", return_value=reaper), \
             patch.object(menu_provider.MenuProvider, "load_menu_data") as load_menu_data:
            provider.start_menu_cache()
            assert provider.menu_cache_process is process
            callbacks[0](process)
        load_menu_data.assert_called_once_with(True, cache=False)

    def test_unmodified_cache_does_not_reload(self):
        from xpra.server import menu_provider

        class Process:
            pid = 1234
            returncode = 0
            stdout = StringIO("modified=0\n")

        process = Process()
        reaper = Mock()
        callbacks = []
        reaper.add_process.side_effect = lambda _proc, _name, _cmd, **kwargs: callbacks.append(kwargs["callback"])
        provider = menu_provider.MenuProvider()
        with patch.object(menu_provider, "POSIX", True), \
             patch.object(menu_provider, "OSX", False), \
             patch.object(menu_provider, "Popen", return_value=process), \
             patch("xpra.platform.paths.get_xpra_command", return_value=["xpra"]), \
             patch("xpra.util.child_reaper.get_child_reaper", return_value=reaper), \
             patch.object(menu_provider.MenuProvider, "load_menu_data") as load_menu_data:
            provider.start_menu_cache()
            callbacks[0](process)
        load_menu_data.assert_not_called()


def main():
    unittest.main()


if __name__ == "__main__":
    main()
