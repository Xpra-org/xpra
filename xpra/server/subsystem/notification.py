# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.
# pylint: disable-msg=E1101

import os.path
from typing import Any
from collections.abc import Sequence

from xpra.os_util import OSX, POSIX, gi_import
from xpra.util.str_fn import Ellipsizer
from xpra.net.common import Packet
from xpra.util.thread import start_thread
from xpra.server.subsystem.stub import StubServerMixin
from xpra.log import Logger

log = Logger("notify")

glib = gi_import("GLib")


class NotificationForwarder(StubServerMixin):
    """
    Mixin for servers that forward notifications.
    """
    PREFIX = "notification"

    def __init__(self):
        StubServerMixin.__init__(self)
        self.notifications_forwarder = None
        self.notifications = False

    def init(self, opts) -> None:
        self.notifications = opts.notifications

    def setup(self) -> None:
        self.init_notification_forwarder()

    def cleanup(self) -> None:
        nf = self.notifications_forwarder
        if nf:
            self.notifications_forwarder = None
            start_thread(nf.release, "notifier-release", daemon=True)

    def get_info(self, _source=None) -> dict[str, Any]:
        if not self.notifications_forwarder:
            return {}
        return {"notifications": self.notifications_forwarder.get_info()}

    def get_server_features(self, _source=None) -> dict[str, Any]:
        return {
            "notifications": {
                "enabled": self.notifications,
            },
        }

    def init_notification_forwarder(self) -> None:
        log("init_notification_forwarder() enabled=%s", self.notifications)
        if self.notifications and POSIX and not OSX:
            try:
                from xpra.dbus.notifications import register
                self.notifications_forwarder = register(self.notify_callback, self.notify_close_callback)
                if self.notifications_forwarder:
                    log.info("D-Bus notification forwarding is available")
                    log("%s", self.notifications_forwarder)
            except Exception as e:
                log("init_notification_forwarder()", exc_info=True)
                self.notify_setup_error(e)

    def notify_setup_error(self, exception) -> None:
        log.warn("Warning: cannot forward notifications,")
        if str(exception).endswith("is already claimed on the session bus"):
            log.warn(" the interface is already claimed")
        else:
            log.warn(" failed to load or register our dbus notifications forwarder:")
            for msg in str(exception).split(": "):
                log.warn(" %s", msg)
        log.warn(" if you do not have a dedicated dbus session for this xpra instance,")
        log.warn(" use the 'notifications=no' option")

    def notify_new_user(self, ss) -> None:
        # tell other users:
        log("notify_new_user(%s) sources=%s", ss, self._server_sources)
        if not self._server_sources:
            return
        try:
            # pylint: disable=import-outside-toplevel
            from xpra.common import NotificationID
            from xpra.notification.common import parse_image_path
            from xpra.platform.paths import get_icon_filename
            icon = parse_image_path(get_icon_filename("user"))
            name = ss.name or ss.username or ss.uuid
            title = f"User {name!r} connected to the session"
            body = "\n".join(ss.get_connect_info())
            for s in self._server_sources.values():
                if s != ss:
                    s.notify("", NotificationID.NEW_USER, "Xpra", 0, "", title, body, [], {}, 10 * 1000, icon)
        except Exception as e:
            log("%s(%s)", self.notify_new_user, ss, exc_info=True)
            log.error("Error: failed to show notification of user login:")
            log.estr(e)

    def notify_callback(self, dbus_id: str, nid: int, app_name: str, replaces_nid: int, app_icon: str,
                        summary: str, body: str,
                        actions: Sequence[str], hints: dict, expire_timeout: int) -> None:
        assert self.notifications_forwarder and self.notifications
        # make sure that we run in the main thread:
        glib.idle_add(self.do_notify_callback, dbus_id, nid,
                      app_name, replaces_nid, app_icon,
                      summary, body,
                      actions, hints, expire_timeout)

    def do_notify_callback(self, dbus_id: str, nid: int,
                           app_name: str, replaces_nid: int, app_icon: str,
                           summary: str, body: str,
                           actions, hints, expire_timeout: int) -> None:
        try:
            icon = self.get_notification_icon(str(app_icon))
            if os.path.isabs(str(app_icon)):
                app_icon = ""
            log("notify_callback%s icon=%s",
                (dbus_id, nid, app_name, replaces_nid, app_icon,
                 summary, body, actions, hints, expire_timeout), Ellipsizer(icon))
            for ss in self._server_sources.values():
                ss.notify(dbus_id, nid, app_name, replaces_nid, app_icon,
                          summary, body, actions, hints, expire_timeout, icon)
        except Exception as e:
            log("notify_callback failed", exc_info=True)
            log.error("Error processing notification:")
            log.estr(e)

    def get_notification_icon(self, icon_string: str) -> tuple[str, int, int, bytes] | None:
        try:
            from xpra.notification.common import get_notification_icon
        except ImportError:
            return None
        return get_notification_icon(icon_string)

    def notify_close_callback(self, nid: int) -> None:
        assert self.notifications_forwarder
        log("notify_close_callback(%s)", nid)
        for ss in self._server_sources.values():
            ss.notify_close(int(nid))

    def _process_notification_status(self, proto, packet: Packet) -> None:
        assert self.notifications, "cannot toggle notifications: the feature is disabled"
        ss = self.get_server_source(proto)
        if ss:
            ss.send_notifications = bool(packet[1])

    def _process_notification_close(self, proto, packet: Packet) -> None:
        assert self.notifications
        nid = packet.get_u64(1)
        reason = packet.get_str(2)
        text = packet.get_str(3)
        ss = self.get_server_source(proto)
        assert ss
        log("closing notification %s: %s, %s", nid, reason, text)
        try:
            # remove client callback if we have one:
            ss.notification_callbacks.pop(nid)
        except KeyError:
            if self.notifications_forwarder:
                # regular notification forwarding:
                active = self.notifications_forwarder.is_notification_active(nid)
                log("notification-close nid=%s, reason=%s, text=%s, active=%s", nid, reason, text, active)
                if active:
                    # an invalid type of the arguments can crash dbus!
                    assert int(nid) >= 0
                    assert int(reason) >= 0
                    self.notifications_forwarder.NotificationClosed(nid, reason)

    def _process_notification_action(self, proto, packet: Packet) -> None:
        assert self.notifications
        nid = packet.get_u64(1)
        action_key = packet.get_str(2)
        ss = self.get_server_source(proto)
        assert ss
        ss.emit("user-event", "notification-action")
        try:
            # special client callback notification:
            client_callback = ss.notification_callbacks.pop(nid)
        except KeyError:
            if self.notifications_forwarder:
                # regular notification forwarding:
                active = self.notifications_forwarder.is_notification_active(nid)
                log("notification-action nid=%i, action key=%s, active=%s", nid, action_key, active)
                if active:
                    self.notifications_forwarder.ActionInvoked(nid, action_key)
        else:
            log("notification callback for %s: %s", (nid, action_key), client_callback)
            client_callback(nid, action_key)

    def init_packet_handlers(self) -> None:
        if self.notifications:
            self.add_packets("notification-close", "notification-action", "notification-status", main_thread=True)
            self.add_legacy_alias("set-notify", "notification-status")
