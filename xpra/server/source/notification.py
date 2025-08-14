# -*- coding: utf-8 -*-
# This file is part of Xpra.
# Copyright (C) 2010-2023 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.util import typedict
from typing import Dict, Any, Callable, Optional

from xpra.server.source.stub_source_mixin import StubSourceMixin
from xpra.log import Logger

log = Logger("notify")


class NotificationMixin(StubSourceMixin):

    @classmethod
    def is_needed(cls, caps : typedict) -> bool:
        v = caps.get("notifications")
        if isinstance(v, bool):
            return v
        if isinstance(v, dict):
            return typedict(v).boolget("enabled", False)
        return False


    def init_state(self) -> None:
        self.send_notifications : bool = False
        self.send_notifications_actions : bool = False
        self.notification_callbacks : Dict[int,Callable] = {}

    def parse_client_caps(self, c : typedict) -> None:
        v = c.get("notifications")
        if isinstance(v, dict):
            c = typedict(v)
            self.send_notifications = c.boolget("enabled")
            self.send_notifications_actions = c.boolget("actions")
        elif isinstance(v, bool):
            self.send_notifications = c.boolget("notifications")
            self.send_notifications_actions = c.boolget("notifications.actions")
        log("notifications=%s, actions=%s", self.send_notifications, self.send_notifications_actions)

    def get_info(self) -> Dict[str,Any]:
        return {
            "notifications" : self.send_notifications,
            }

    ######################################################################
    # notifications:
    # Utility functions for mixins (makes notifications optional)
    def may_notify(self, nid:int=0, summary:str="", body:str="",    #pylint: disable=arguments-differ
                   actions=(), hints=None, expire_timeout=10*1000,
                   icon_name:str="", user_callback:Optional[Callable]=None) -> None:
        try:
            from xpra.platform.paths import get_icon_filename
            from xpra.notifications.common import parse_image_path
        except ImportError as e:
            log("not sending notification: %s", e)
        else:
            icon_filename = get_icon_filename(icon_name)
            icon = parse_image_path(icon_filename)
            self.notify("", int(nid), "Xpra", 0, "",
                        summary, body, actions, hints or {},
                        expire_timeout, icon, user_callback)

    def notify(self, dbus_id, nid:int, app_name:str, replaces_nid:int, app_icon,
               summary:str, body:str, actions, hints, expire_timeout:int, icon, user_callback:Optional[Callable]=None) -> bool:
        args = (dbus_id, nid, app_name, replaces_nid, app_icon, summary, body, actions, hints, expire_timeout, icon)
        log("notify%s types=%s", args, tuple(type(x) for x in args))
        if not self.send_notifications:
            log("client %s does not support notifications", self)
            return False
        #"suspended" belongs in the WindowsMixin:
        if getattr(self, "suspended", False):
            log("client %s is suspended, notification not sent", self)
            return False
        if user_callback:
            self.notification_callbacks[nid] = user_callback
        if self.hello_sent:
            #Warning: actions and hints are send last because they were added later (in version 2.3)
            self.send_async("notify_show", dbus_id, nid, app_name, replaces_nid, app_icon,
                            summary, body, expire_timeout, icon or b"", actions, hints)
        return True

    def notify_close(self, nid : int) -> None:
        if not self.send_notifications or self.suspended  or not self.hello_sent:
            return
        self.send_more("notify_close", nid)
