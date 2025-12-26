# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys
from typing import Any

from xpra.common import BACKWARDS_COMPATIBLE
from xpra.os_util import gi_import
from xpra.client.base.client import XpraClientBase, EXTRA_TIMEOUT
from xpra.exit_codes import ExitValue, ExitCode
from xpra.log import Logger

log = Logger("gobject", "client")

GObject = gi_import("GObject")
GLib = gi_import("GLib")


class GObjectXpraClient(GObject.GObject, XpraClientBase):
    """
        Utility superclass for GObject clients
    """
    COMMAND_TIMEOUT = EXTRA_TIMEOUT

    def __init__(self):
        self.glib_mainloop = None
        GObject.GObject.__init__(self)
        XpraClientBase.__init__(self)
        self.client_type = "pygobject"

    def init(self, opts) -> None:
        XpraClientBase.init(self, opts)

    def install_signal_handlers(self) -> None:
        from xpra.util.glib import install_signal_handlers
        install_signal_handlers("%s Client" % self.client_type, self.handle_app_signal)

    def make_protocol(self, conn):
        protocol = super().make_protocol(conn)
        protocol._log_stats = False
        GLib.idle_add(self.send_hello)
        return protocol

    def run(self) -> ExitValue:
        XpraClientBase.run(self)
        self.glib_mainloop = GLib.MainLoop()
        self.run_loop()
        return self.exit_code or ExitCode.OK

    def run_loop(self) -> None:
        self.glib_mainloop.run()

    def make_hello(self) -> dict[str, Any]:
        capabilities = XpraClientBase.make_hello(self)
        if BACKWARDS_COMPATIBLE:
            capabilities["keyboard"] = False
        return capabilities

    def quit(self, exit_code: ExitValue = ExitCode.OK) -> None:
        log("quit(%s) current exit_code=%s", exit_code, self.exit_code)
        if self.exit_code is None:
            self.exit_code = exit_code
        self.exit_loop()
        # if for some reason cleanup() hangs, maybe this will fire...
        GLib.timeout_add(4 * 1000, self.exit)
        # try harder!:
        GLib.timeout_add(5 * 1000, self.force_quit, exit_code)

    def exit_loop(self) -> None:
        self.glib_mainloop.quit()
        self.cleanup()

    def exit(self) -> None:
        self.show_progress(100, "terminating")
        log(f"exit() calling {sys.exit}")
        sys.exit(int(self.exit_code or ExitCode.OK))
