# -*- coding: utf-8 -*-
# This file is part of Xpra.
# Copyright (C) 2010-2020 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.util import typedict
from xpra.server.source.stub_source_mixin import StubSourceMixin
from xpra.log import Logger

log = Logger("notify")


class NotificationMixin(StubSourceMixin):

    @classmethod
    def is_needed(cls, caps : typedict) -> bool:
        return caps.boolget("notifications", False)

    def __init__(self, *_args):
        pass

    def init_state(self):
        self.send_notifications = False
        self.send_notifications_actions = False
        self.notification_callbacks = {}

    def parse_client_caps(self, c : typedict):
        self.send_notifications = c.boolget("notifications")
        self.send_notifications_actions = c.boolget("notifications.actions")
        log("notifications=%s, actions=%s", self.send_notifications, self.send_notifications_actions)

    def get_info(self) -> dict:
        return {
            "notifications" : self.send_notifications,
            }

    ######################################################################
    # notifications:
    # Utility functions for mixins (makes notifications optional)
    def may_notify(self, nid=0, summary="", body="",    #pylint: disable=arguments-differ
                   actions=(), hints=None, expire_timeout=10*1000,
                   icon_name=None, user_callback=None):
        try:
            from xpra.platform.paths import get_icon_filename
            from xpra.notifications.common import parse_image_path
        except ImportError as e:
            log("not sending notification: %s", e)
        else:
            icon_filename = get_icon_filename(icon_name)
            icon = parse_image_path(icon_filename) or ""
            self.notify("", nid, "Xpra", 0, "",
                        summary, body, actions, hints or {},
                        expire_timeout, icon, user_callback)

    def notify(self, dbus_id, nid, app_name, replaces_nid, app_icon,
               summary, body, actions, hints, expire_timeout, icon, user_callback=None):
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
        #this is one of the few places where we actually do care about character encoding:
        try:
            summary = summary.encode("utf8")
        except UnicodeEncodeError:
            summary = str(summary)
        try:
            body = body.encode("utf8")
        except UnicodeEncodeError:
            body = str(body)
        if self.hello_sent:
            #Warning: actions and hints are send last because they were added later (in version 2.3)
            self.send_async("notify_show", dbus_id, nid, app_name, replaces_nid, app_icon,
                            summary, body, expire_timeout, icon, actions, hints)
        return True

    def notify_close(self, nid : int):
        if not self.send_notifications or self.suspended  or not self.hello_sent:
            return
        self.send_more("notify_close", nid)
