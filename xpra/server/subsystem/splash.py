# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from subprocess import Popen

from xpra.log import Logger
from xpra.server.subsystem.stub import StubServerMixin

log = Logger("server")


# noinspection PyMethodMayBeStatic
class SplashServer(StubServerMixin):
    """
        Manages the splash screen
    """

    def __init__(self):
        log("ServerCore.__init__()")
        self.splash_process: Popen | None = None

    def setup(self) -> None:
        self.stop_splash_process()

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
