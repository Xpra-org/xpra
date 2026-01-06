# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from subprocess import Popen

from xpra.common import noop, SPLASH_EXIT_DELAY
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
        StubServerMixin.__init__(self)
        log("SplashServer()")
        self.splash_process: Popen | None = None

    def setup(self) -> None:
        def running() -> bool:
            progress = getattr(self.splash_process, "progress", noop)
            progress(100, "running")
            GLib.timeout_add(SPLASH_EXIT_DELAY * 1000 + 100, self.stop_splash_process)
            return False
        GLib.idle_add(running)

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
