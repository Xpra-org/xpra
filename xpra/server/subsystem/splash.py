# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from subprocess import Popen

from xpra.log import Logger
from xpra.os_util import gi_import
from xpra.server.subsystem.stub import StubServerMixin

log = Logger("server")

GLib = gi_import("GLib")


# noinspection PyMethodMayBeStatic
class SplashServer(StubServerMixin):
    """
        Manages the splash screen
    """

    def __init__(self):
        log("ServerCore.__init__()")
        self.splash_process: Popen | None = None

    def setup(self) -> None:
        GLib.timeout_add(0, self.stop_splash_process)

    def cleanup(self) -> None:
        self.stop_splash_process()

    def stop_splash_process(self) -> None:
        sp = self.splash_process
        if sp:
            self.splash_process = None
            try:
                sp.terminate()
            except OSError:
                log("stop_splash_process()", exc_info=True)
