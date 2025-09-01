# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.
# pylint: disable-msg=E1101

from xpra.server.subsystem.stub import StubServerMixin
from xpra.platform.events import add_handler, remove_handler
from xpra.log import Logger

log = Logger("event")


class PowerEventServer(StubServerMixin):
    """
    Adds power events callbacks
    """

    def setup(self) -> None:
        add_handler("suspend", self.suspend_event)
        add_handler("resume", self.resume_event)

    def cleanup(self) -> None:
        remove_handler("suspend", self.suspend_event)
        remove_handler("resume", self.resume_event)

    @staticmethod
    def suspend_event(*_args) -> None:
        log.info("suspending")

    @staticmethod
    def resume_event(*_args) -> None:
        log.info("resuming")
