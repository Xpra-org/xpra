# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.
# pylint: disable-msg=E1101

from typing import Any
from collections.abc import Sequence, Callable

from xpra.common import noop
from xpra.constants import NotificationID
from xpra.platform.paths import get_icon_filename
from xpra.platform.notification import get_backends
from xpra.net.common import Packet, BACKWARDS_COMPATIBLE
from xpra.util.objects import typedict, make_instance
from xpra.util.str_fn import repr_ellipsized, csv
from xpra.util.env import envbool
from xpra.client.base.stub import StubClientMixin
from xpra.log import Logger

log = Logger("notify")

NATIVE_NOTIFIER = envbool("XPRA_NATIVE_NOTIFIER", True)
THREADED_NOTIFICATIONS = envbool("XPRA_THREADED_NOTIFICATIONS", True)


notifier = None


class NotificationClient(StubClientMixin):
    """
    Mixin for clients that handle notifications
    """
    PREFIX = "notification"

    def __init__(self):
        self.client_supports = False
        self.server = False
        self.enabled = False
        self.notifier = None
        self.tray = None
        self.callbacks: dict[int, Callable] = {}

    def init(self, opts) -> None:
        self.enabled = opts.notifications

    def load(self):
        if not self.enabled:
            return
        try:
            from xpra import notification
            if not notification:
                # cythonized code can bind None for missing imports
                raise ImportError("xpra.notification")
        except ImportError:
            log.warn("Warning: notification module not found")
            self.enabled = False
            return
        self.client_supports = True
        self.notifier = self.make_notifier()
        log("using notifier=%s", self.notifier)
        self.enabled = self.notifier is not None
        self.client_supports = self.notifier is not None
        global notifier
        notifier = self.notifier

    def cleanup(self) -> None:
        n = self.notifier
        log("NotificationClient.cleanup() notifier=%s", n)
        if n:
            self.notifier = None
            with log.trap_error(f"Error on notifier {n!r} cleanup"):
                n.cleanup()
            global notifier
            notifier = None

    def parse_server_capabilities(self, c: typedict) -> bool:
        self.server = ("notifications" if BACKWARDS_COMPATIBLE else "notification") in c
        self.enabled = self.client_supports
        return True

    def get_caps(self) -> dict[str, Any]:
        enabled = self.client_supports
        caps: dict[str, Any] = {
            NotificationClient.PREFIX: enabled,
        }
        if BACKWARDS_COMPATIBLE:
            caps["notifications"] = {
                "enabled": enabled,
            }
        return caps

    def make_notifier(self):
        nc = self.client.get_notifier_classes()
        log("make_notifier() notifier classes: %s", csv(nc))
        return make_instance(nc, self.notification_closed, self.notification_action)

    def notification_closed(self, nid: int, reason=3, text="") -> None:
        log("notification_closed(%i, %i, %s)", nid, reason, text)
        if callback := self.callbacks.pop(nid, None):
            callback("notification-close", nid, reason, text)
        elif self.server:
            self.send("notification-close", nid, reason, text)

    def notification_action(self, nid: int, action_id: str) -> None:
        log("notification_action(%i, %s)", nid, action_id)
        if callback := self.callbacks.get(nid, None):
            callback("notification-action", nid, action_id)
        elif self.server:
            self.send("notification-action", nid, action_id)

    @staticmethod
    def get_native_notifier_classes() -> Sequence[Callable]:
        # the toolkit-independent (native) notifiers;
        # the concrete client's `get_notifier_classes` composes these with its
        # own toolkit-specific variants (see `UIXpraClient.get_notifier_classes`).
        ncs = get_backends() if NATIVE_NOTIFIER else ()
        log("get_native_notifier_classes() %s.%s()=%s (native=%s)",
            get_backends.__module__, get_backends.__name__, ncs, NATIVE_NOTIFIER)
        return ncs

    def notify_client(self, nid: int | NotificationID, summary: str, body: str, actions: Sequence[str] = (),
                      hints: dict | None = None, expire_timeout=10 * 1000, icon_name: str = "", callback=noop) -> None:
        log("notify_client%s client_supports=%s, notifier=%s",
            (nid, summary, body, actions, hints, expire_timeout, icon_name),
            self.client_supports, self.notifier)
        if callback:
            self.callbacks[nid] = callback
        n = self.notifier
        if not self.client_supports or not n:
            # just log it instead:
            log.info("%s", summary)
            if body:
                for x in body.splitlines():
                    log.info(" %s", x)
            return

        def show_notification() -> None:
            try:
                from xpra.notification.common import parse_image_path
                icon_filename = get_icon_filename(icon_name)
                icon = parse_image_path(icon_filename)
                n.show_notify("", self.tray, int(nid), "Xpra", int(nid), "",
                              summary, body, actions, hints or {}, expire_timeout, icon)
            except Exception as e:
                log("failed to show notification", exc_info=True)
                log.error("Error: cannot show notification")
                log.error(" '%s'", summary)
                log.estr(e)

        if THREADED_NOTIFICATIONS:
            show_notification()
        else:
            self.idle_add(show_notification)

    def supported_icon_data(self, icon_data, what="icon"):
        # drop icon data we have no decoder for,
        # weak dependency on the `Encodings` subsystem:
        encoding = self.get_subsystem("encoding")
        core_encodings = encoding.get_core_encodings() if encoding else ()
        if icon_data and icon_data[0] not in core_encodings:
            log.warn(f"Warning: unsupported notification {what} encoding {icon_data[0]!r}")
            log.warn(f" supported encodings: {csv(core_encodings)}")
            return None
        return icon_data

    def _process_notification_show(self, packet: Packet) -> None:
        if not self.enabled:
            log("process_notify_show: ignoring packet, notifications are disabled")
            return
        self.client._ui_event()
        dbus_id = packet.get_str(1)
        nid = packet.get_u64(2)
        app_name = packet.get_str(3)
        replaces_nid = packet.get_u64(4)
        app_icon = packet.get_str(5)
        summary = packet.get_str(6)
        body = packet.get_str(7)
        expire_timeout = packet.get_i64(8)
        icon = None
        actions: Sequence[str] = ()
        hints = {}
        if len(packet) >= 10:
            # IconData or ()
            icon = packet[9]
        if len(packet) >= 12:
            actions = packet.get_strs(10)
            hints = packet.get_dict(11)
        # only allow icon encodings we actually have a decoder for:
        icon = self.supported_icon_data(icon, "icon")
        app_icon_data = hints.get("app-icon-data")
        if app_icon_data and not self.supported_icon_data(app_icon_data, "app-icon"):
            hints.pop("app-icon-data")
        # note: if the server doesn't support notification forwarding,
        # it can still send us the messages (via xpra control or the dbus interface)
        log("_process_notification_show(%s) notifier=%s, server=%s",
            repr_ellipsized(packet), self.notifier, self.server)
        log("notification actions=%s, hints=%s", actions, hints)
        assert self.notifier
        # this one of the few places where we actually do care about character encoding:
        # `get_tray_window` is owned by the `window` subsystem (which may be disabled):
        window = self.get_subsystem("window")
        tray = window.get_tray_window(app_name, hints) if window else None
        log("get_tray_window(%s)=%s", app_name, tray)
        self.notifier.show_notify(dbus_id, tray, nid,
                                  app_name, replaces_nid, app_icon,
                                  summary, body, actions, hints, expire_timeout, icon)

    def _process_notification_close(self, packet: Packet) -> None:
        if not self.enabled:
            return
        assert self.notifier
        nid = packet.get_u64(1)
        log("_process_notification_close(%s)", nid)
        self.notifier.close_notify(nid)

    def init_authenticated_packet_handlers(self) -> None:
        self.add_packets(f"{NotificationClient.PREFIX}-show", f"{NotificationClient.PREFIX}-close", main_thread=True)
        self.add_legacy_alias("notify_show", f"{NotificationClient.PREFIX}-show")
        self.add_legacy_alias("notify_close", f"{NotificationClient.PREFIX}-close")
