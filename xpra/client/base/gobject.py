# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.os_util import gi_import
from xpra.client.base.client import EXTRA_TIMEOUT
from xpra.exit_codes import ExitValue, ExitCode
from xpra.util.glib_scheduler import GLibScheduler
from xpra.log import Logger

log = Logger("gobject", "client")

GObject = gi_import("GObject")
GLib = gi_import("GLib")


class GObjectClientAdapter(GObject.GObject, GLibScheduler):
    """
        Utility mixin for GObject clients
        adds the main loop.
    """
    COMMAND_TIMEOUT = EXTRA_TIMEOUT

    def __init__(self):
        self.exit_code = None
        self.glib_mainloop = None
        self.client_type = "pygobject"
        GObject.GObject.__init__(self)

    def install_signal_handlers(self) -> None:
        from xpra.util.glib import install_signal_handlers
        install_signal_handlers("%s Client" % self.client_type, self.handle_app_signal)

    def run(self) -> ExitValue:
        self.glib_mainloop = GLib.MainLoop()
        self.run_loop()
        return self.exit_code or ExitCode.OK

    def run_loop(self) -> None:
        self.glib_mainloop.run()

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

    def connect(self, name: str, *args, **kwargs) -> int:
        try:
            return super().connect(name, *args, **kwargs)
        except TypeError:
            log(f"ignoring missing signal {name!r}")
            return 0
