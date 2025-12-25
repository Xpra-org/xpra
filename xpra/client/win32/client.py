# This file is part of Xpra.
# Copyright (C) 2025 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import signal

from xpra.exit_codes import ExitValue
from xpra.os_util import gi_import
from xpra.client.gui.ui_client_base import UIXpraClient
from xpra.log import Logger

log = Logger("client")
netlog = Logger("client", "network")

GLib = gi_import("GLib")


class XpraWin32Client(UIXpraClient):

    def __init__(self):
        super().__init__()

    def client_toolkit(self) -> str:
        return "Win32"

    def get_root_size(self):
        from xpra.platform.win32.gui import get_display_size
        return get_display_size()

    def run(self) -> int:
        super().run()
        self.mainloop = GLib.MainLoop()
        self.mainloop.run()
        return 0

    def quit(self, exit_code: ExitValue = 0) -> None:
        if self.exit_code is None:
            self.exit_code = exit_code
        self.mainloop.quit()


def make_client() -> XpraWin32Client:
    signal.signal(signal.SIGINT, signal.SIG_DFL)
    return XpraWin32Client()


def run_client(host: str, port: int) -> int:
    client = make_client()
    client.connect(host, port)
    return client.run()
