# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import sys
from subprocess import Popen

from xpra import __version__
from xpra.common import noop
from xpra.os_util import POSIX, OSX
from xpra.scripts.main import SPLASH_EXIT_DELAY, make_progress_process
from xpra.util.io import stderr_print
from xpra.util.env import envbool, get_saved_env_var
from xpra.log import Logger
from xpra.os_util import gi_import
from xpra.server.subsystem.stub import StubSubsystem

log = Logger("server", "splash")

PROGRESS_TO_STDERR = envbool("XPRA_PROGRESS_TO_STDERR", False)

MODE_TO_NAME: dict[str, str] = {
    "seamless": "Seamless",
    "desktop": "Desktop",
    "monitor": "Monitor",
    "expand": "Expand",
    "upgrade": "Upgrade",
    "upgrade-seamless": "Seamless Upgrade",
    "upgrade-desktop": "Desktop Upgrade",
    "upgrade-monitor": "Monitor Upgrade",
    "shadow": "Shadow",
    "shadow-screen": "Shadow Screen",
    "proxy": "Proxy",
}


def is_splash_enabled(mode: str, daemon: bool, splash: bool | None, display: str) -> bool:
    log("is_splash_enabled%s", (mode, daemon, splash, display))
    if daemon:
        # daemon mode would have problems with the pipes
        return False
    if splash in (True, False):
        return splash
    # auto mode, figure out if we should show it:
    if os.environ.get("SSH_CONNECTION") or os.environ.get("SSH_CLIENT"):
        log("no splash: don't show over SSH forwarding")
        return False
    xdisplay = get_saved_env_var("DISPLAY")
    if xdisplay and not mode.startswith("shadow") and xdisplay == display:
        log("no splash: same display we're running on")
        return False
    if mode in ("proxy", "encoder", "runner"):
        log("no splash: %r mode", mode)
        return False
    if not POSIX or OSX:
        log("splash enabled on %r", sys.platform)
        return True
    if desktop := get_saved_env_var("XDG_SESSION_DESKTOP"):
        log("splash shown on %r", desktop)
        return True
    log("no splash on %r", sys.platform)
    return False


# noinspection PyMethodMayBeStatic
class SplashServer(StubSubsystem):
    """
        Manages the splash screen
    """
    PREFIX = "splash"

    def __init__(self, server=None):
        StubSubsystem.__init__(self, server)
        log("SplashServer()")
        self.splash_process: Popen | None = None
        self.mode = ""
        self.daemon = False
        self.splash = False
        self.progress_fn = noop

    def init(self, opts) -> None:
        self.mode = str(opts.mode)
        self.daemon = bool(opts.daemon)
        self.splash = opts.splash

    def setup_splash(self, display_name: str) -> None:
        self.progress_fn = noop
        use_stderr = PROGRESS_TO_STDERR
        if is_splash_enabled(self.mode, self.daemon, self.splash, display_name):
            mode_str = MODE_TO_NAME.get(self.mode, "").split(" Upgrade")[0]
            title = f"Xpra {mode_str} Server {__version__}"
            self.splash_process = make_progress_process(title)
            if self.splash_process:
                self.progress_fn = self.splash_process.progress
                from atexit import register

                def progress_exit() -> None:
                    self.progress(100, "exiting")
                register(progress_exit)
            else:
                use_stderr = True
        if self.progress_fn == noop and use_stderr:
            def progress_to_stderr(*args) -> None:
                stderr_print(" ".join(str(x) for x in args))

            self.progress_fn = progress_to_stderr
        self.progress(10, "initializing environment")

    def progress(self, pct: int, msg: str) -> None:
        self.progress_fn(pct, msg)

    def setup(self) -> None:
        GLib = gi_import("GLib")

        def running() -> bool:
            self.progress(100, "running")
            GLib.timeout_add(SPLASH_EXIT_DELAY * 1000 + 100, self.stop_splash_process)
            return False
        GLib.idle_add(running)

    def cleanup(self) -> None:
        self.stop_splash_process()

    def stop_splash_process(self) -> None:
        if sp := self.splash_process:
            self.splash_process = None
            try:
                sp.terminate()
            except OSError:
                log("stop_splash_process()", exc_info=True)
