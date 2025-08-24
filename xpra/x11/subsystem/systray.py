# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.server.subsystem.stub import StubServerMixin
from xpra.x11.error import xsync
from xpra.log import Logger

log = Logger("server", "tray")


class SystemTrayServer(StubServerMixin):

    def __init__(self):
        StubServerMixin.__init__(self)
        self.system_tray = False
        self._tray = None

    def init(self, opts) -> None:
        self.system_tray = opts.system_tray

    def setup(self) -> None:
        if self.system_tray:
            self.init_system_tray()

    def cleanup(self) -> None:
        tray = self._tray
        if tray:
            self._tray = None
            tray.cleanup()

    def init_system_tray(self) -> None:
        try:
            with xsync:
                from xpra.x11.tray import SystemTray
                self._tray = SystemTray()
        except RuntimeError as e:
            log("init_system_tray()", exc_info=True)
            log.error("Error: unable to setup system tray forwarding")
            log.estr(e)
