# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

# the key shortcut actions which belong to the client rather than to the window,
# the shortcuts can only reach the client through these names
# (the `--key-shortcut` option must not be able to call just any client method, ie: `cleanup`):
CLIENT_ACTIONS: frozenset[str] = frozenset((
    "quit",
    "show_menu",
    "show_session_info",
    "show_start_new_command",
    "show_bug_report",
    "show_file_upload",
    "show_shortcuts",
    "show_docs",
    "configure_server_debug",
    "show_debug_config",
))


class ShortcutTarget:
    """
    What the key shortcut actions are invoked on (`KeyboardHelper.key_handled_as_shortcut`):
    the actions implemented here, then the window's own methods,
    then the client's `CLIENT_ACTIONS`.
    """

    def __init__(self, client, window):
        self.client = client
        self.window = window

    def __repr__(self):
        return f"ShortcutTarget({self.window})"

    def __getattr__(self, name: str):
        # (only called for the names which are not defined here)
        if hasattr(self.window, name):
            return getattr(self.window, name)
        if name in CLIENT_ACTIONS and hasattr(self.client, name):
            return getattr(self.client, name)
        raise AttributeError(f"no shortcut action {name!r} for {self.window}")

    def void(self, *_args) -> None:
        """
        This method can be used to capture key shortcuts
        without triggering any specific action.
        """

    def download_server_log(self, *_args) -> None:
        # the client's argument is a callback, not something a shortcut can supply:
        self.client.download_server_log()
