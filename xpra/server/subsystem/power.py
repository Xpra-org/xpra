# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.
# pylint: disable-msg=E1101

from xpra.server.common import get_sources_by_type
from xpra.server.subsystem.stub import StubServerMixin
from xpra.platform.events import add_handler, remove_handler
from xpra.common import may_notify_client
from xpra.util.env import envbool
from xpra.constants import NotificationID
from xpra.log import Logger

log = Logger("event")

NOTIFY_SUSPEND_EVENTS = envbool("XPRA_NOTIFY_SUSPEND_EVENTS", True)

NOTIFY_MESSAGE_TITLE = "Server Suspending"
NOTIFY_MESSAGE_BODY = "This Xpra server is going to suspend,\nthe connection is likely to be interrupted soon."


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

    def suspend_event(self, *args) -> None:
        log("suspend_event%s", args)
        log.info("suspending")
        if NOTIFY_SUSPEND_EVENTS:
            try:
                from xpra.server.source.notification import NotificationConnection
            except ImportError:
                return
            notify_sources = get_sources_by_type(self, NotificationConnection)
            for source in notify_sources:
                may_notify_client(source, NotificationID.IDLE, NOTIFY_MESSAGE_TITLE, NOTIFY_MESSAGE_BODY,
                                  expire_timeout=10 * 1000, icon_name="shutdown")

    @staticmethod
    def resume_event(self, *args) -> None:
        log("resume_event%s", args)
        log.info("resuming")
