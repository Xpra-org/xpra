# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from Quartz.CoreGraphics import CGDisplayRegisterReconfigurationCallback, CGDisplayRemoveReconfigurationCallback
from Quartz import kCGDisplaySetModeFlag

from xpra.log import Logger

log = Logger("osx", "events")


class DarwinDisplayReconfigWatcher:
    """
    Watches for display (GPU) reconfiguration events, re-creating OpenGL
    windows when needed, feeding the `display` subsystem.
    """

    def __init__(self, display_client):
        self.display = display_client

    def setup(self) -> None:
        r = CGDisplayRegisterReconfigurationCallback(self.cg_display_change, self)
        if r != 0:
            log.warn("Warning: failed to register display reconfiguration callback")

    def cleanup(self) -> None:
        try:
            r = CGDisplayRemoveReconfigurationCallback(self.cg_display_change, self)
        except ValueError as e:
            log("CGDisplayRemoveReconfigurationCallback: %s", e)
            # if we exit from a signal, this may fail
            r = 1
        if r != 0:
            # don't bother logging this as a warning since we are terminating anyway:
            log("failed to unregister display reconfiguration callback")

    def cg_display_change(self, display, flags, userinfo) -> None:
        log("cg_display_change%s", (display, flags, userinfo))
        if not (flags & kCGDisplaySetModeFlag):
            # The display mode has not changed.
            return
        # opengl windows may need to be re-created since the GPU may have changed:
        opengl = self.display.get_subsystem("opengl")
        window = self.display.get_subsystem("window")
        if opengl and window and opengl.enabled:
            window.reinit_windows()
