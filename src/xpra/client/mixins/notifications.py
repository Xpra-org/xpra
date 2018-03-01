# This file is part of Xpra.
# Copyright (C) 2010-2018 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.log import Logger
log = Logger("notify")


from xpra.platform.paths import get_icon_filename
from xpra.platform.gui import get_native_notifier_classes
from xpra.os_util import bytestostr
from xpra.util import envbool, repr_ellipsized, make_instance
from xpra.client.mixins.stub_client_mixin import StubClientMixin


NATIVE_NOTIFIER = envbool("XPRA_NATIVE_NOTIFIER", True)


"""
Utility superclass for clients that handle notifications
"""
class NotificationClient(StubClientMixin):

    def __init__(self):
        StubClientMixin.__init__(self)
        self.client_supports_notifications = False
        self.notifications_enabled = False
        self.notifier = None
        self.tray = None

    def init(self, opts):
        if opts.notifications:
            try:
                from xpra import notifications
                assert notifications
            except ImportError:
                log.warn("Warning: notifications module not found")
            else:
                self.client_supports_notifications = True

    def init_ui(self):
        log("client_supports_notifications=%s", self.client_supports_notifications)
        if self.client_supports_notifications:
            self.notifier = self.make_notifier()
            log("using notifier=%s", self.notifier)
            self.client_supports_notifications = self.notifier is not None


    def cleanup(self):
        n = self.notifier
        log("NotificationClient.cleanup() notifier=%s", n)
        if n:
            self.notifier = None
            try:
                n.cleanup()
            except:
                log.error("Error on notifier cleanup", exc_info=True)


    def parse_server_capabilities(self):
        c = self.server_capabilities
        self.server_notifications = c.boolget("notifications")
        self.server_notifications_close = c.boolget("notifications.close")
        self.server_notifications_actions = c.boolget("notifications.actions")
        self.notifications_enabled = self.client_supports_notifications
        return True


    def get_notifications_caps(self):
        return {
            ""            : self.client_supports_notifications,
            "close"       : self.client_supports_notifications,
            "actions"     : self.client_supports_notifications and self.notifier and self.notifier.handles_actions,
            }

    def init_authenticated_packet_handlers(self):
        self.set_packet_handlers(self._ui_packet_handlers, {
            "notify_show":          self._process_notify_show,
            "notify_close":         self._process_notify_close,
            })

    def make_notifier(self):
        nc = self.get_notifier_classes()
        log("make_notifier() notifier classes: %s", nc)
        return make_instance(nc, self.notification_closed, self.notification_action)

    def notification_closed(self, nid, reason=3, text=""):
        log("notification_closed(%i, %i, %s) server notification.close=%s", nid, reason, text, self.server_notifications_close)
        if self.server_notifications_close:
            self.send("notification-close", nid, reason, text)

    def notification_action(self, nid, action_id):
        log("notification_action(%i, %s) server notifications.actions=%s", nid, action_id, self.server_notifications_actions)
        if self.server_notifications_actions:
            self.send("notification-action", nid, action_id)

    def get_notifier_classes(self):
        #subclasses will generally add their toolkit specific variants
        #by overriding this method
        #use the native ones first:
        if not NATIVE_NOTIFIER:
            return []
        return get_native_notifier_classes()

    def may_notify(self, nid, summary, body, actions=[], hints={}, expire_timeout=10*1000, icon_name=None):
        log("may_notify%s client_supports_notifications=%s, notifier=%s", (nid, summary, body, actions, hints, expire_timeout, icon_name), self.client_supports_notifications, self.notifier)
        n = self.notifier
        if not self.client_supports_notifications or not n:
            return
        try:
            from xpra.notifications.common import parse_image_path
            icon_filename = get_icon_filename(icon_name)
            icon = parse_image_path(icon_filename)
            n.show_notify("", self.tray, nid, "Xpra", nid, "", summary, body, actions, hints, expire_timeout, icon)
        except Exception as e:
            log("failed to show notification", exc_info=True)
            log.error("Error: cannot show notification")
            log.error(" '%s'", summary)
            log.error(" %s", e)

    def _process_notify_show(self, packet):
        if not self.notifications_enabled:
            log("process_notify_show: ignoring packet, notifications are disabled")
            return
        self._ui_event()
        dbus_id, nid, app_name, replaces_nid, app_icon, summary, body, expire_timeout = packet[1:9]
        icon, actions, hints = None, [], {}
        if len(packet)>=10:
            icon = packet[9]
        if len(packet)>=12:
            actions, hints = packet[10], packet[11]
        #note: if the server doesn't support notification forwarding,
        #it can still send us the messages (via xpra control or the dbus interface)
        log("_process_notify_show(%s) notifier=%s, server_notifications=%s", repr_ellipsized(str(packet)), self.notifier, self.server_notifications)
        log("notification actions=%s, hints=%s", actions, hints)
        assert self.notifier
        #this one of the few places where we actually do care about character encoding:
        try:
            summary = summary.decode("utf8")
        except:
            summary = bytestostr(summary)
        try:
            body = body.decode("utf8")
        except:
            body = bytestostr(body)
        app_name = bytestostr(app_name)
        tray = self.get_tray_window(app_name, hints)
        log("get_tray_window(%s)=%s", app_name, tray)
        self.notifier.show_notify(dbus_id, tray, nid, app_name, replaces_nid, app_icon, summary, body, actions, hints, expire_timeout, icon)

    def _process_notify_close(self, packet):
        if not self.notifications_enabled:
            return
        assert self.notifier
        nid = packet[1]
        log("_process_notify_close(%s)", nid)
        self.notifier.close_notify(nid)

    def get_tray_window(self, _app_name, _hints):
        #overriden in subclass to use the correct window if we can find it
        return self.tray
