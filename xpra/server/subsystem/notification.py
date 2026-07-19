# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.
# pylint: disable-msg=E1101

import os.path
from typing import Any
from collections.abc import Sequence

from xpra.os_util import OSX, POSIX
from xpra.server.source.notification import NotificationConnection
from xpra.util.str_fn import Ellipsizer
from xpra.net.common import Packet, BACKWARDS_COMPATIBLE
from xpra.util.thread import start_thread
from xpra.server.subsystem.stub import StubSubsystem
from xpra.log import Logger

log = Logger("notify")


class NotificationForwarder(StubSubsystem):
    """
    Mixin for servers that forward notifications.
    """
    __slots__ = ("enabled", "forwarder")
    PREFIX = "notifications" if BACKWARDS_COMPATIBLE else "notification"
    toggle_features = ("notifications",)

    def __init__(self, server=None):
        StubSubsystem.__init__(self, server)
        self.forwarder = None
        self.enabled = False

    def init(self, opts) -> None:
        self.enabled = opts.notifications

    def setup(self) -> None:
        self.init_notification_forwarder()
        self.add_notification_control_commands()

    def add_notification_control_commands(self) -> None:
        ac = self.args_control
        ac("send-notification", "sends a notification to the client(s)", min_args=4, max_args=5, validation=[int])
        ac("close-notification", "send the request to close an existing notification to the client(s)", min_args=1, max_args=2, validation=[int])

    def cleanup(self) -> None:
        if nf := self.forwarder:
            self.forwarder = None
            start_thread(nf.release, "notifier-release", daemon=True)

    def get_info(self, _source=None) -> dict[str, Any]:
        if not self.forwarder:
            return {}
        return {NotificationForwarder.PREFIX: self.forwarder.get_info()}

    def get_server_features(self, _source=None) -> dict[str, Any]:
        return {
            NotificationForwarder.PREFIX: {
                "enabled": self.enabled,
            },
        }

    def init_notification_forwarder(self) -> None:
        log("init_notification_forwarder() enabled=%s", self.enabled)
        if self.enabled and POSIX and not OSX:
            try:
                from xpra.dbus.notifications import register
                self.forwarder = register(self.notify_callback, self.notify_close_callback)
                if self.forwarder:
                    log.info("D-Bus notification forwarding is available")
                    log("%s", self.forwarder)
            except Exception as e:
                log("init_notification_forwarder()", exc_info=True)
                self.server.notify_setup_error(e)

    def notify_new_user(self, ss) -> None:
        # tell other users:
        notification_sources = self.get_sources_by_type(NotificationConnection, ss)
        log("notify_new_user(%s) sources=%s", ss, notification_sources)
        if not notification_sources:
            return
        try:
            # pylint: disable=import-outside-toplevel
            from xpra.constants import NotificationID
            from xpra.notification.common import parse_image_path
            from xpra.platform.paths import get_icon_filename
            icon = parse_image_path(get_icon_filename("user"))
            name = ss.name or ss.username or ss.uuid
            title = f"User {name!r} connected to the session"
            body = "\n".join(ss.get_connect_info())
            for s in notification_sources:
                s.notify("", NotificationID.NEW_USER, "Xpra", 0, "", title, body, [], {}, 10 * 1000, icon)
        except Exception as e:
            log("%s(%s)", self.notify_new_user, ss, exc_info=True)
            log.error("Error: failed to show notification of user login:")
            log.estr(e)

    def notify_callback(self, dbus_id: str, nid: int, app_name: str, replaces_nid: int, app_icon: str,
                        summary: str, body: str,
                        actions: Sequence[str], hints: dict, expire_timeout: int) -> None:
        assert self.forwarder and self.enabled
        # make sure that we run in the main thread:
        self.idle_add(self.do_notify_callback, dbus_id, nid,
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
            notification_sources = self.get_sources_by_type(NotificationConnection)
            for ss in notification_sources:
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
        assert self.forwarder
        log("notify_close_callback(%s)", nid)
        notification_sources = self.get_sources_by_type(NotificationConnection)
        for ss in notification_sources:
            ss.notify_close(int(nid))

    def _process_notification_status(self, proto, packet: Packet) -> None:
        assert self.enabled, "cannot toggle notifications: the feature is disabled"
        if ss := self.get_server_source(proto):
            ss.send_notifications = packet.get_bool(1)

    def _process_notification_close(self, proto, packet: Packet) -> None:
        assert self.enabled
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
            if self.forwarder:
                # regular notification forwarding:
                active = self.forwarder.is_notification_active(nid)
                log("notification-close nid=%s, reason=%s, text=%s, active=%s", nid, reason, text, active)
                if active:
                    # an invalid type of the arguments can crash dbus!
                    assert int(nid) >= 0
                    assert int(reason) >= 0
                    self.forwarder.NotificationClosed(nid, reason)

    def _process_notification_action(self, proto, packet: Packet) -> None:
        assert self.enabled
        nid = packet.get_u64(1)
        action_key = packet.get_str(2)
        ss = self.get_server_source(proto)
        assert ss
        ss.user_event("notification-action")
        try:
            # special client callback notification:
            client_callback = ss.notification_callbacks.pop(nid)
        except KeyError:
            if self.forwarder:
                # regular notification forwarding:
                active = self.forwarder.is_notification_active(nid)
                log("notification-action nid=%i, action key=%s, active=%s", nid, action_key, active)
                if active:
                    self.forwarder.ActionInvoked(nid, action_key)
        else:
            log("notification callback for %s: %s", (nid, action_key), client_callback)
            client_callback(nid, action_key)

    def init_packet_handlers(self) -> None:
        if self.enabled:
            self.add_packets("notification-close", "notification-action", "notification-status", main_thread=True)
            self.add_legacy_alias("set-notify", "notification-status")

    #########################################
    # Control Commands
    #########################################

    def control_command_send_notification(self, nid: int, title: str, message: str, client_uuids) -> str:
        if not self.enabled:
            msg = "notification are disabled"
            log(msg)
            return msg
        from xpra.net.control.common import control_get_sources
        sources = control_get_sources(self.server, client_uuids)
        log("control_command_send_notification(%i, %s, %s, %s) will send to sources %s (matching %s)",
            nid, title, message, client_uuids, sources, client_uuids)
        count = 0
        for source in sources:
            if source.notify(0, nid, "control channel", 0, "", title, message, [], {}, 10, ""):
                count += 1
        msg = f"notification id {nid}: message sent to {count} clients"
        log(msg)
        return msg

    def control_command_close_notification(self, nid: int, client_uuids) -> str:
        if not self.enabled:
            msg = "notification are disabled"
            log(msg)
            return msg
        from xpra.net.control.common import control_get_sources
        sources = control_get_sources(self.server, client_uuids)
        log("control_command_close_notification(%s, %s) will send to %s", nid, client_uuids, sources)
        for source in sources:
            source.notify_close(nid)
        msg = f"notification id {nid}: close request sent to {len(sources)} clients"
        log(msg)
        return msg
