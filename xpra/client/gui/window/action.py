# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.client.gui.window.stub_window import StubWindow


class ActionWindow(StubWindow):
    """
    This module adds actions that can be used with key shortcuts
    """

    def quit(self) -> None:
        self._client.quit(0)

    def void(self) -> None:
        """
        This method can be used to capture key shortcuts
        without triggering any specific action.
        """

    def show_window_info(self, *_args) -> None:
        from xpra.client.gtk3.window.window_info import WindowInfo
        wi = WindowInfo(self._client, self)
        wi.show()

    def show_session_info(self, *args) -> None:
        self._client.show_session_info(*args)

    def show_menu(self, *args) -> None:
        self._client.show_menu(*args)

    def show_start_new_command(self, *args) -> None:
        self._client.show_start_new_command(*args)

    def show_bug_report(self, *args) -> None:
        self._client.show_bug_report(*args)

    def show_file_upload(self, *args) -> None:
        self._client.show_file_upload(*args)

    def show_shortcuts(self, *args) -> None:
        self._client.show_shortcuts(*args)

    def show_docs(self, *args) -> None:
        self._client.show_docs(*args)

    def download_server_log(self, *_args) -> None:
        self._client.download_server_log()

    def configure_server_debug(self, *args) -> None:
        self._client.configure_server_debug(*args)

    def show_debug_config(self, *args) -> None:
        self._client.show_debug_config(*args)
