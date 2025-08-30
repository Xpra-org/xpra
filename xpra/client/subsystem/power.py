# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.
# pylint: disable-msg=E1101

from xpra.client.base.stub import StubClientMixin
from xpra.log import Logger

log = Logger("event")


class PowerEventClient(StubClientMixin):
    """
    Adds power events callbacks
    """

    def __init__(self):
        self.ui_watcher = None

    def run(self) -> None:
        try:
            self.connect("first-ui-received", self.start_ui_watcher)
        except (TypeError, AttributeError):
            log("no 'first-ui-received' signal")
        from xpra.platform.events import add_handler
        add_handler("suspend", self.suspend)
        add_handler("resume", self.resume)

    def start_ui_watcher(self, _client) -> None:
        from xpra.platform.uithreadwatcher import get_ui_watcher
        self.ui_watcher = get_ui_watcher()
        assert self.ui_watcher
        self.ui_watcher.start()
        self.ui_watcher.add_resume_callback(self.resume_os_event)
        self.ui_watcher.add_fail_callback(self.suspend_os_event)

    def cleanup(self) -> None:
        from xpra.platform.events import remove_handler
        remove_handler("suspend", self.suspend_os_event)
        remove_handler("resume", self.resume_os_event)
        uw = self.ui_watcher
        if uw:
            self.ui_watcher = None
            uw.stop()

    def ui_thread_tick(self):
        uiw = self.ui_watcher
        if uiw:
            uiw.tick()

    def suspend_os_event(self):
        self.ui_thread_tick()
        self.suspend()

    def resume_os_event(self):
        self.ui_thread_tick()
        self.resume()

    def suspend(self) -> None:
        log.info(f"{self} suspending")

    def resume(self) -> None:
        log.info(f"{self} resuming")
