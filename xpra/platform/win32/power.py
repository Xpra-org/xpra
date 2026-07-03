# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.platform.win32 import constants as win32con
from xpra.platform.win32.common import GetIntSystemParametersInfo
from xpra.util.env import envint
from xpra.os_util import gi_import
from xpra.log import Logger

log = Logger("win32", "events")

GLib = gi_import("GLib")

SCREENSAVER_LISTENER_POLL_DELAY = envint("XPRA_SCREENSAVER_LISTENER_POLL_DELAY", 10)


class Win32ScreensaverWatcher:
    """
    Polls the screensaver state as a proxy for suspend/resume, feeding the
    `power` subsystem.
    """

    def __init__(self, power_client):
        self.power = power_client
        self._screensaver_state = False
        self._screensaver_timer = 0

    def setup(self) -> None:
        if SCREENSAVER_LISTENER_POLL_DELAY > 0:
            self._screensaver_timer = GLib.timeout_add(SCREENSAVER_LISTENER_POLL_DELAY * 1000, self.poll_screensaver)

    def cleanup(self) -> None:
        if sst := self._screensaver_timer:
            self._screensaver_timer = 0
            GLib.source_remove(sst)

    def poll_screensaver(self) -> bool:
        v = bool(GetIntSystemParametersInfo(win32con.SPI_GETSCREENSAVERRUNNING))
        log("SPI_GETSCREENSAVERRUNNING=%s", v)
        if self._screensaver_state != v:
            self._screensaver_state = v
            if v:
                self.power.suspend()
            else:
                self.power.resume()
        return True
