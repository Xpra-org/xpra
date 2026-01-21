# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.
# pylint: disable-msg=E1101

from time import time
from datetime import timedelta

from xpra.client.base.stub import StubClientMixin
from xpra.common import BACKWARDS_COMPATIBLE
from xpra.log import Logger

log = Logger("event")


class PowerEventClient(StubClientMixin):
    """
    Adds power events callbacks
    """
    __signals__: list[str] = ["suspend", "resume"]

    def __init__(self):
        self.ui_watcher = None
        self.suspended = 0.0

    def run(self) -> None:
        try:
            self.connect("first-ui-received", self.start_ui_watcher)
        except (TypeError, AttributeError):
            log("no 'first-ui-received' signal")
        from xpra.platform.events import add_handler
        add_handler("suspend", self.suspend)
        add_handler("resume", self.resume)

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
        uw = self.ui_watcher
        if uw:
            self.ui_watcher = None
            uw.stop()

    def ui_thread_tick(self):
        uiw = self.ui_watcher
        if uiw:
            uiw.tick()

    def ui_pause(self):
        self.ui_thread_tick()
        self.pause()

    def ui_unpause(self):
        self.ui_thread_tick()
        self.unpause()

    def ui_message(self, message: str) -> None:
        if self.suspended:
            log(message)
        else:
            log.info(message)

    def pause(self) -> None:
        log(f"{self} pause")

    def unpause(self) -> None:
        log(f"{self} unpause")

    def suspend(self) -> None:
        log.info(f"{self} suspending")
        self.suspended = time()
        self.emit("suspend")
        if BACKWARDS_COMPATIBLE:
            # ("ui" and "window-ids" arguments are optional since v6.3)
            self.send("suspend", True, tuple(self._id_to_window.keys()))
        else:
            self.send("suspend")

    def resume(self) -> None:
        self.emit("resume")
        elapsed = max(0.0, time() - self.suspended) if self.suspended else 0.0
        if BACKWARDS_COMPATIBLE:
            self.send("resume", True, tuple(self._id_to_window.keys()))
        else:
            self.send("resume")
        if elapsed < 1:
            # not really suspended
            # happens on macos when switching workspace!
            return
        delta = timedelta(seconds=int(elapsed))
        log.info(f"{self} resuming, was suspended for %s", str(delta).lstrip("0:"))
