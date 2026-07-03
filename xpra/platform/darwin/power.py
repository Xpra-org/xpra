# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import Quartz.CoreGraphics as CG

from xpra.platform.darwin.gui import can_access_display
from xpra.os_util import gi_import
from xpra.log import Logger

log = Logger("osx", "events")
GLib = gi_import("GLib")


class DarwinDisplaySleepWatcher:
    """
    Polls the main display's sleep state as a proxy for suspend/resume,
    feeding the `power` subsystem.
    """

    def __init__(self, power_client):
        self.power = power_client
        self.check_display_timer = 0
        self.display_is_asleep = False

    def setup(self) -> None:
        self.check_display_timer = GLib.timeout_add(60 * 1000, self.cg_check_display)

    def cleanup(self) -> None:
        if cdt := self.check_display_timer:
            GLib.source_remove(cdt)
            self.check_display_timer = 0

    def cg_check_display(self) -> bool:
        log("cg_check_display()")
        try:
            asleep = None
            if not can_access_display():
                asleep = True
            else:
                did = CG.CGMainDisplayID()
                log("cg_check_display() CGMainDisplayID()=%#x", did)
                if did:
                    asleep = bool(CG.CGDisplayIsAsleep(did))
                    log("cg_check_display() CGDisplayIsAsleep(%#x)=%s", did, asleep)
            if asleep is not None and self.display_is_asleep != asleep:
                self.display_is_asleep = asleep
                if asleep:
                    self.power.suspend()
                else:
                    self.power.resume()
            return True
        except Exception:
            log.error("Error checking display sleep status", exc_info=True)
            self.check_display_timer = 0
            return False
