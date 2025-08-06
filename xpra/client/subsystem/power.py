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

    def run(self) -> None:
        from xpra.platform.events import add_handler
        add_handler("suspend", self.suspend)
        add_handler("resume", self.resume)

    def cleanup(self) -> None:
        from xpra.platform.events import remove_handler
        remove_handler("suspend", self.suspend)
        remove_handler("resume", self.resume)

    def suspend(self) -> None:
        log.info(f"{self} suspending")

    def resume(self) -> None:
        log.info(f"{self} resuming")
