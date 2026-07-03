# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.
# pylint: disable-msg=E1101

from time import time
from datetime import timedelta

from xpra.client.base.stub import StubClientMixin
from xpra.net.common import BACKWARDS_COMPATIBLE
from xpra.os_util import WIN32, OSX
from xpra.util.env import envint
from xpra.log import Logger

log = Logger("event")

FAKE_SUSPEND_RESUME: int = envint("XPRA_FAKE_SUSPEND_RESUME", 0)


class PowerEventClient(StubClientMixin):
    """
    Adds power events callbacks
    """
    PREFIX = "power"
    __signals__: list[str] = ["suspend", "resume", "pause", "unpause"]

    def __init__(self, client=None):
        StubClientMixin.__init__(self, client)
        self.ui_watcher = None
        self.suspended = 0.0
        # extra, platform-specific suspend/resume signal sources feeding the
        # same `suspend()`/`resume()` below:
        self._platform_watcher = None

    def run(self) -> None:
        try:
            self.client.connect("first-ui-received", self.start_ui_watcher)
        except (TypeError, AttributeError):
            log("no 'first-ui-received' signal")
        from xpra.platform.events import add_handler
        add_handler("suspend", self.suspend)
        add_handler("resume", self.resume)
        if FAKE_SUSPEND_RESUME:
            def fake_suspend() -> bool:
                self.suspend()
                self.timeout_add(FAKE_SUSPEND_RESUME * 500, self.resume)
                return True
            self.timeout_add(FAKE_SUSPEND_RESUME * 1000, fake_suspend)
        if WIN32:
            from xpra.platform.win32.power import Win32ScreensaverWatcher
            self._platform_watcher = Win32ScreensaverWatcher(self)
        elif OSX:
            from xpra.platform.darwin.power import DarwinDisplaySleepWatcher
            self._platform_watcher = DarwinDisplaySleepWatcher(self)
        if self._platform_watcher:
            self._platform_watcher.setup()

    def start_ui_watcher(self, _client) -> None:
        if self.ui_watcher:
            return
        from xpra.util.ui_thread_watcher import get_ui_watcher
        self.ui_watcher = get_ui_watcher()
        assert self.ui_watcher
        self.ui_watcher.start()
        self.ui_watcher.add_resume_callback(self.ui_unpause)
        self.ui_watcher.add_fail_callback(self.ui_pause)
        self.ui_watcher.show_message = self.ui_message

    def cleanup(self) -> None:
        from xpra.platform.events import remove_handler
        remove_handler("suspend", self.suspend)
        remove_handler("resume", self.resume)
        if uw := self.ui_watcher:
            self.ui_watcher = None
            uw.stop()
        if pw := self._platform_watcher:
            self._platform_watcher = None
            pw.cleanup()

    def ui_thread_tick(self):
        if uiw := self.ui_watcher:
            uiw.tick()

    def ui_pause(self):
        self.ui_thread_tick()
        self.emit("pause")

    def ui_unpause(self):
        self.ui_thread_tick()
        self.emit("unpause")

    def ui_message(self, message: str) -> None:
        if self.suspended:
            log(message)
        else:
            log.info(message)

    def suspend(self, *args) -> None:
        log("suspend(%s)", args)
        log.info(f"{self} suspending")
        self.suspended = time()
        self.emit("suspend")
        if BACKWARDS_COMPATIBLE:
            # ("ui" and "window-ids" arguments are optional since v6.3)
            win = self.get_subsystem("window")
            wids = tuple(win._id_to_window.keys()) if win else ()
            self.send("suspend", True, wids)
        else:
            self.send("suspend")

    def resume(self, *args) -> None:
        log("resume(%s)", args)
        self.emit("resume")
        elapsed = max(0.0, time() - self.suspended) if self.suspended else 0.0
        self.suspended = 0.0
        if BACKWARDS_COMPATIBLE:
            win = self.get_subsystem("window")
            wids = tuple(win._id_to_window.keys()) if win else ()
            self.send("resume", True, wids)
        else:
            self.send("resume")
        if elapsed < 1:
            # not really suspended
            # happens on macos when switching workspace!
            return
        delta = timedelta(seconds=int(elapsed))
        log.info(f"{self} resuming, was suspended for %s", str(delta).lstrip("0:"))
