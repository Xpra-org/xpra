# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.
# pylint: disable-msg=E1101

from xpra.server.subsystem.stub import StubServerMixin


class UIWatcher(StubServerMixin):
    """
    Monitors the UI thread
    """

    def __init__(self):
        StubServerMixin.__init__(self)
        self.ui_watcher = None

    def run(self) -> None:
        from xpra.platform.ui_thread_watcher import get_ui_watcher  # pylint: disable=import-outside-toplevel
        self.ui_watcher = get_ui_watcher()
        self.ui_watcher.start()

    def cleanup(self, stop=True) -> None:
        uiw = self.ui_watcher
        if uiw:
            self.ui_watcher = None
            uiw.stop()
