# -*- coding: utf-8 -*-
# This file is part of Xpra.
# Copyright (C) 2010-2018 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os.path

from xpra.log import Logger
log = Logger("server")
notifylog = Logger("notify")

from xpra.os_util import thread, OSX, POSIX
from xpra.util import repr_ellipsized
from xpra.server.mixins.stub_server_mixin import StubServerMixin


"""
Mixin for servers that forward notifications.
"""
class NotificationForwarder(StubServerMixin):

    def __init__(self):
        self.notifications_forwarder = None
        self.notifications = False

    def init(self, opts):
        self.notifications = opts.notifications

    def setup(self):
        self.init_notification_forwarder()

    def cleanup(self):
        nf = self.notifications_forwarder
        if nf:
            self.notifications_forwarder = None
            thread.start_new_thread(nf.release, ())

    def get_info(self, _source=None):
        if not self.notifications_forwarder:
            return {}
        return {"notifications" : self.notifications_forwarder.get_info()}

    def get_server_features(self, _source=None):
        return {
            "notifications"                : self.notifications,
            "notifications.close"          : self.notifications,
            "notifications.actions"        : self.notifications,
            }


    def init_notification_forwarder(self):
        log("init_notification_forwarder() enabled=%s", self.notifications)
        if self.notifications and POSIX and not OSX:
            try:
                from xpra.dbus.notifications_forwarder import register
                self.notifications_forwarder = register(self.notify_callback, self.notify_close_callback)
                if self.notifications_forwarder:
                    log.info("D-Bus notification forwarding is available")
                    log("%s", self.notifications_forwarder)
            except Exception as e:
                log("init_notification_forwarder()", exc_info=True)
                self.notify_setup_error(e)

    def notify_setup_error(self, exception):
        if str(exception).endswith("is already claimed on the session bus"):
            log.warn("Warning: cannot forward notifications, the interface is already claimed")
        else:
            log.warn("Warning: failed to load or register our dbus notifications forwarder:")
            log.warn(" %s", exception)
        log.warn(" if you do not have a dedicated dbus session for this xpra instance,")
        log.warn(" use the 'notifications=no' option")


    def notify_callback(self, dbus_id, nid, app_name, replaces_nid, app_icon, summary, body, actions, hints, expire_timeout):
        try:
            assert self.notifications_forwarder and self.notifications
            icon = self.get_notification_icon(str(app_icon))
            if os.path.isabs(str(app_icon)):
                app_icon = ""
            notifylog("notify_callback%s icon=%s", (dbus_id, nid, app_name, replaces_nid, app_icon, summary, body, actions, hints, expire_timeout), repr_ellipsized(str(icon)))
            for ss in self._server_sources.values():
                ss.notify(dbus_id, nid, app_name, replaces_nid, app_icon, summary, body, actions, hints, expire_timeout, icon)
        except Exception as e:
            notifylog("notify_callback failed", exc_info=True)
            notifylog.error("Error processing notification:")
            notifylog.error(" %s", e)

    def get_notification_icon(self, _icon_string):
        return []

    def notify_close_callback(self, nid):
        assert self.notifications_forwarder and self.notifications
        notifylog("notify_close_callback(%s)", nid)
        for ss in self._server_sources.values():
            ss.notify_close(int(nid))


    def _process_set_notify(self, proto, packet):
        assert self.notifications, "cannot toggle notifications: the feature is disabled"
        ss = self._server_sources.get(proto)
        if ss:
            ss.send_notifications = bool(packet[1])

    def _process_notification_close(self, proto, packet):
        assert self.notifications
        nid, reason, text = packet[1:4]
        ss = self._server_sources.get(proto)
        assert ss
        try:
            #remove client callback if we have one:
            ss.notification_callbacks.pop(nid)
        except KeyError:
            if self.notifications_forwarder:
                #regular notification forwarding:
                active = self.notifications_forwarder.is_notification_active(nid)
                notifylog("notification-close nid=%i, reason=%i, text=%s, active=%s", nid, reason, text, active)
                if active:
                    self.notifications_forwarder.NotificationClosed(nid, reason)

    def _process_notification_action(self, proto, packet):
        assert self.notifications
        nid, action_key = packet[1:3]
        ss = self._server_sources.get(proto)
        assert ss
        ss.user_event()
        try:
            #special client callback notification:
            client_callback = ss.notification_callbacks.pop(nid)
        except KeyError:
            if self.notifications_forwarder:
                #regular notification forwarding:
                active = self.notifications_forwarder.is_notification_active(nid)
                notifylog("notification-action nid=%i, action key=%s, active=%s", nid, action_key, active)
                if active:
                    self.notifications_forwarder.ActionInvoked(nid, action_key)
        else:
            client_callback(nid, action_key)


    def init_packet_handlers(self):
        self._authenticated_ui_packet_handlers.update({
            #notifications:
            "notification-close":                   self._process_notification_close,
            "notification-action":                  self._process_notification_action,
            "set-notify":                           self._process_set_notify,
            })
