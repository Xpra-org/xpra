# This file is part of Xpra.
# Copyright (C) 2011 Serviware (Arthur Huillet, <ahuillet@serviware.com>)
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys
from typing import Any
from collections.abc import Callable, Sequence

from xpra.client.gui.factory import get_client_base_classes
from xpra.client.base.client import XpraClientBase
from xpra.platform import set_name
from xpra.platform.gui import ready as gui_ready, get_wm_name, get_session_type
from xpra.common import FULL_INFO, NotificationID, ConnectionMessage, noerr, get_run_info, BACKWARDS_COMPATIBLE
from xpra.net.common import Packet, print_proxy_caps
from xpra.os_util import gi_import
from xpra.util.child_reaper import reaper_cleanup
from xpra.util.objects import typedict
from xpra.util.str_fn import Ellipsizer, repr_ellipsized
from xpra.util.env import envint, envbool
from xpra.exit_codes import ExitCode, ExitValue
from xpra.client.base import features
from xpra.log import Logger

CLIENT_BASES = get_client_base_classes()
ClientBaseClass = type('ClientBaseClass', CLIENT_BASES, {})

GLib = gi_import("GLib")

log = Logger("client")
log("UIXpraClient base classes: %s", CLIENT_BASES)

NOTIFICATION_EXIT_DELAY = envint("XPRA_NOTIFICATION_EXIT_DELAY", 2)
FORCE_ALERT = envbool("XPRA_FORCE_ALERT", False)


class UIXpraClient(ClientBaseClass):
    """
    Utility superclass for client classes which have a UI.
    See gtk_client_base and its subclasses.
    """
    # NOTE: these signals aren't registered here because this class
    # does not extend GObject,
    # the gtk client subclasses will take care of it.
    # these are all "no-arg" signals
    __signals__ = ["first-ui-received", ]
    for c in CLIENT_BASES:
        if c != XpraClientBase:
            __signals__ += c.__signals__

    # noinspection PyMissingConstructor
    def __init__(self):  # pylint: disable=super-init-not-called
        # try to ensure we start on a new line (see #4023):
        noerr(sys.stdout.write, "\n")
        run_info = get_run_info(f"{self.client_toolkit()} client")
        wm = get_wm_name()  # pylint: disable=assignment-from-none
        if wm:
            run_info.append(f" window manager is {wm!r}")
        for info in run_info:
            log.info(info)
        # same for tray:
        self.tray = None
        for c in CLIENT_BASES:
            log("calling %s.__init__()", c)
            c.__init__(self)  # pylint: disable=non-parent-init-called
        self._ui_events: int = 0
        self.title: str = ""
        self.session_name: str = ""
        self.server_session_name: str = ""

        # features:
        self.readonly: bool = False
        self.headerbar = None
        self.suspended = False

        # in WindowClient - should it be?
        # self.server_is_desktop = False
        self.server_sharing: bool = False
        self.server_sharing_toggle: bool = False
        self.server_lock: bool = False
        self.server_lock_toggle: bool = False
        self.server_pointer: bool = True
        self.server_readonly = False
        self.server_setting_updates: dict[str, Any] = {}

        self.client_supports_sharing: bool = False
        self.client_lock: bool = False

        # state:
        self._on_handshake: Sequence[tuple[Callable, Sequence[Any]]] | None = []
        self._on_server_setting_changed: dict[str, Sequence[Callable[[str, Any], None]]] = {}

    def init(self, opts) -> None:
        """ initialize variables from configuration """
        for c in CLIENT_BASES:
            log(f"init: {c}")
            c.init(self, opts)

        self.title = opts.title
        self.session_name = opts.session_name
        self.readonly = opts.readonly
        self.client_supports_sharing = opts.sharing is True
        self.client_lock = opts.lock is True
        self.headerbar = opts.headerbar

    def client_toolkit(self) -> str:
        raise NotImplementedError()

    def init_ui(self, opts) -> None:
        """ initialize user interface """
        for c in CLIENT_BASES:
            log(f"init: {c}")
            c.init_ui(self, opts)

    def run(self) -> ExitValue:
        if FORCE_ALERT:
            self.schedule_timer_redraw()
        for c in CLIENT_BASES:
            c.run(self)
        return self.exit_code or 0

    def quit(self, exit_code: ExitValue = 0) -> None:
        raise NotImplementedError()

    def cleanup(self) -> None:
        log("UIXpraClient.cleanup()")
        for c in CLIENT_BASES:
            c.cleanup(self)
        # the protocol has been closed, it is now safe to close all the windows:
        # (cleaner and needed when we run embedded in the client launcher)
        reaper_cleanup()
        log("UIXpraClient.cleanup() done")

    def signal_cleanup(self) -> None:
        log("UIXpraClient.signal_cleanup()")
        XpraClientBase.signal_cleanup(self)
        reaper_cleanup()
        log("UIXpraClient.signal_cleanup() done")

    def get_info(self) -> dict[str, Any]:
        info: dict[str, Any] = {}
        if FULL_INFO > 0:
            info["session-name"] = self.session_name
        for c in CLIENT_BASES:
            with log.trap_error("Error collection information from %s", c):
                info.update(c.get_info(self))
        return info

    def suspend(self, *args) -> None:
        log("suspend%s", args)
        self.suspended = True
        for c in CLIENT_BASES:
            c.suspend(self)
        # tell the server:
        # ("ui" and "window-ids" arguments are optional since v6.3)
        self.send("suspend", True, tuple(self._id_to_window.keys()))

    def resume(self, *args) -> None:
        log("resume%s", args)
        self.suspended = False
        for c in CLIENT_BASES:
            c.resume(self)
        # tell the server:
        # ("ui" and "window-ids" arguments are optional since v6.3)
        self.send("resume", True, tuple(self._id_to_window.keys()))

    def show_about(self, *_args) -> None:
        log.warn(f"show_about() is not implemented in {self!r}")

    def show_session_info(self, *_args) -> None:
        log.warn(f"show_session_info() is not implemented in {self!r}")

    def show_bug_report(self, *_args) -> None:
        log.warn(f"show_bug_report() is not implemented in {self!r}")

    def _ui_event(self) -> None:
        if self._ui_events == 0:
            self.emit("first-ui-received")
        self._ui_events += 1

    def server_ok(self) -> bool:
        # get the real value from the PingClient feature, if present:
        return getattr(self, "_server_ok", True)

    def get_mouse_position(self) -> tuple:
        raise NotImplementedError()

    def get_current_modifiers(self) -> Sequence[str]:
        raise NotImplementedError()

    ######################################################################
    # trigger notifications on disconnection,
    # and wait before actually exiting so the notification has a chance of being seen
    def server_disconnect_warning(self, reason, *info):
        if self.exit_code is None:
            body = "\n".join(info)
            if not self.connection_established:
                if ConnectionMessage.AUTHENTICATION_FAILED.value in info:
                    title = "Authentication failed"
                    self.exit_code = ExitCode.AUTHENTICATION_FAILED
                else:
                    title = "Connection failed: %s" % reason
                    self.exit_code = ExitCode.CONNECTION_FAILED
            else:
                if self.completed_startup:
                    title = "Xpra Session Disconnected: %s" % reason
                    self.exit_code = ExitCode.CONNECTION_LOST
                else:
                    title = "Connection failed during startup: %s" % reason
                    self.exit_code = ExitCode.CONNECTION_FAILED
            self.may_notify(NotificationID.DISCONNECT, title, body, icon_name="disconnected")
            # show text notification then quit:
            delay = NOTIFICATION_EXIT_DELAY * int(features.notification)
            GLib.timeout_add(delay * 1000, XpraClientBase.server_disconnect_warning, self, title, *info)
        self.cleanup()

    def server_disconnect(self, reason: str, *info) -> None:
        body = "\n".join(info)
        self.may_notify(NotificationID.DISCONNECT,
                        f"Xpra Session Disconnected: {reason}", body, icon_name="disconnected")
        delay = NOTIFICATION_EXIT_DELAY * int(features.notification)
        if self.exit_code is None:
            self.exit_code = self.server_disconnect_exit_code(reason, *info)
        GLib.timeout_add(delay * 1000, XpraClientBase.server_disconnect, self, reason, *info)
        self.cleanup()

    ######################################################################
    # hello:
    def make_hello(self) -> dict[str, Any]:
        caps = XpraClientBase.make_hello(self)
        caps.setdefault("wants", []).append("events")
        caps |= {
            "setting-change": True,
            # generic server flags:
            "share": self.client_supports_sharing,
            "lock": self.client_lock,
        }
        for c in CLIENT_BASES:
            caps.update(c.get_caps(self))
        if FULL_INFO > 0:
            caps["session-type"] = get_session_type()
        return caps

    ######################################################################
    # connection setup:
    def setup_connection(self, conn) -> None:
        super().setup_connection(conn)
        for c in CLIENT_BASES:
            if c != XpraClientBase:
                c.setup_connection(self, conn)

    def server_connection_established(self, caps: typedict) -> bool:
        if not XpraClientBase.server_connection_established(self, caps):
            return False
        # process the rest from the UI thread:
        GLib.idle_add(self.process_ui_capabilities, caps)
        return True

    def parse_server_capabilities(self, c: typedict) -> bool:
        for cb in CLIENT_BASES:
            log("%s.parse_server_capabilities(..)", cb)
            try:
                if not cb.parse_server_capabilities(self, c):
                    log.info(f"failed to parse server capabilities in {cb}")
                    return False
            except Exception:
                log("%s.parse_server_capabilities(%s)", cb, Ellipsizer(c))
                log.error("Error parsing server capabilities using %s", cb, exc_info=True)
                return False
        self.server_session_name = c.strget("session_name")
        set_name("Xpra", self.session_name or self.server_session_name or "Xpra")
        self.server_sharing = c.boolget("sharing")
        self.server_sharing_toggle = c.boolget("sharing-toggle")
        self.server_lock = c.boolget("lock")
        self.server_lock_toggle = c.boolget("lock-toggle")
        self.server_readonly = c.boolget("readonly")
        if self.server_readonly and not self.readonly:
            log.info("server is read only")
            self.readonly = True
        print_proxy_caps(c)
        return True

    def process_ui_capabilities(self, caps: typedict) -> None:
        for c in CLIENT_BASES:
            if c != XpraClientBase:
                c.process_ui_capabilities(self, caps)
        self.handshake_complete()

    def _process_startup_complete(self, packet: Packet) -> None:
        log("all the existing windows and system trays have been received")
        super()._process_startup_complete(packet)
        gui_ready()
        for c in CLIENT_BASES:
            c.startup_complete(self)

    def _process_new_window(self, packet: Packet):
        window = super()._process_new_window(packet)
        screen_mode = any(self._remote_server_mode.find(x) >= 0 for x in ("desktop", "monitor", "shadow"))
        if self.desktop_fullscreen and screen_mode:
            Gdk = gi_import("Gdk")
            screen = Gdk.Screen.get_default()
            n = screen.get_n_monitors()
            monitor = (len(self._id_to_window) - 1) % n
            window.fullscreen_on_monitor(screen, monitor)
            log("fullscreen_on_monitor: %i", monitor)
        return window

    def handshake_complete(self) -> None:
        oh = self._on_handshake
        self._on_handshake = None
        for cb, args in oh:
            with log.trap_error("Error processing handshake callback %s", cb):
                cb(*args)

    def after_handshake(self, cb: Callable, *args) -> None:
        log("after_handshake(%s, %s) on_handshake=%s", cb, args, Ellipsizer(self._on_handshake))
        if self._on_handshake is None:
            # handshake has already occurred, just call it:
            GLib.idle_add(cb, *args)
        else:
            self._on_handshake.append((cb, args))

    ######################################################################
    # server messages:
    # noinspection PyMethodMayBeStatic
    def _process_server_event(self, packet: Packet) -> None:
        log(": ".join(str(x) for x in packet[1:]))

    def on_server_setting_changed(self, setting: str, cb: Callable[[str, Any], None]) -> None:
        self._on_server_setting_changed.setdefault(setting, []).append(cb)
        # has the value already been updated:
        value = self.server_setting_updates.get(setting)
        log("on_server_setting_changed%s value=%s", (setting, cb), value)
        if value is not None:
            cb(setting, value)

    def _process_setting_change(self, packet: Packet) -> None:
        setting = packet.get_str(1)
        value = packet[2]
        # convert "hello" / "setting" variable names to client variables:
        if BACKWARDS_COMPATIBLE:
            setting = {"xdg-menu": "menu"}.get(setting, setting)
        if setting in (
            "clipboard-limits",
        ):
            # FIXME: this should update the limits?
            pass
        elif setting in (
                "bell", "randr", "cursors", "notifications", "clipboard",
                "clipboard-direction", "session_name",
                "sharing", "sharing-toggle", "lock", "lock-toggle",
                "start-new-commands", "client-shutdown", "webcam",
                "bandwidth-limit", "clipboard-limits",
                "menu", "monitors",
                "ibus-layouts",
        ):
            setattr(self, "server_%s" % setting.replace("-", "_"), value)
        else:
            log.info("unknown server setting changed: %s=%s", setting, repr_ellipsized(value))
            return
        log("_process_setting_change: %s=%s", setting, Ellipsizer(value))
        # these are too big to log
        if setting not in ("menu", "monitors", "ibus-layouts"):
            log.info("server setting changed: %s=%s", setting, repr_ellipsized(value))
        self.server_setting_changed(setting, value)

    def server_setting_changed(self, setting: str, value) -> None:
        self.server_setting_updates[setting] = value
        cbs: Sequence[Callable[[str, Any], None]] = self._on_server_setting_changed.get(setting, ())
        log("setting_changed(%s, %s) callbacks=%s", setting, Ellipsizer(value, limit=200), cbs)
        for cb in cbs:
            log("setting_changed(%s, %s) calling %s", setting, Ellipsizer(value, limit=200), cb)
            cb(setting, value)

    def add_control_commands(self) -> None:
        super().add_control_commands()
        try:
            from xpra.net.control.common import ControlCommand, ArgsControlCommand
        except ImportError as e:
            log(f"control commands are not available: {e}")
        else:
            self.control_commands |= {
                "show_session_info": ControlCommand("show-session-info", "Shows the session info dialog", self.show_session_info),
                "show_bug_report": ControlCommand("show-bug-report", "Shows the bug report dialog", self.show_bug_report),
                "name": ArgsControlCommand("name", "Sets the server session name", self.set_server_session_name,
                                           min_args=1, max_args=1),
            }

    def set_server_session_name(self, name: str):
        self.server_session_name = name
        log.info("session name updated from server: %s", self.server_session_name)

    def may_notify_audio(self, summary: str, body: str) -> None:
        self.may_notify(NotificationID.AUDIO, summary, body, icon_name="audio")

    ######################################################################
    # features:
    def send_sharing_enabled(self) -> None:
        assert self.server_sharing and self.server_sharing_toggle
        self.send("sharing-toggle", self.client_supports_sharing)

    def send_lock_enabled(self) -> None:
        assert self.server_lock_toggle
        self.send("lock-toggle", self.client_lock)

    def send_notify_enabled(self) -> None:
        assert self.client_supports_notifications, "cannot toggle notifications: the feature is disabled by the client"
        self.send("set-notify", self.notifications_enabled)

    def send_bell_enabled(self) -> None:
        assert self.client_supports_bell, "cannot toggle bell: the feature is disabled by the client"
        assert self.server_bell, "cannot toggle bell: the feature is disabled by the server"
        self.send("set-bell", self.bell_enabled)

    def send_cursors_enabled(self) -> None:
        assert self.client_supports_cursors, "cannot toggle cursors: the feature is disabled by the client"
        assert self.server_cursors, "cannot toggle cursors: the feature is disabled by the server"
        packet_type = "set-cursors" if BACKWARDS_COMPATIBLE else "cursor-set"
        self.send(packet_type, self.cursors_enabled)

    def send_force_ungrab(self, wid: int) -> None:
        self.send("force-ungrab", wid)

    def send_keyboard_sync_enabled_status(self, *_args) -> None:
        self.send("set-keyboard-sync-enabled", self.keyboard_sync)

    ######################################################################
    # windows overrides
    def cook_metadata(self, _new_window, metadata: dict) -> typedict:
        # convert to a typedict and apply client-side overrides:
        tdmeta = typedict(metadata)
        if self.server_is_desktop and self.desktop_fullscreen:
            # force it fullscreen:
            metadata.pop("size-constraints", None)
            metadata["fullscreen"] = True
            # FIXME: try to figure out the monitors we go fullscreen on for X11:
            # if POSIX:
            #    metadata["fullscreen-monitors"] = [0, 1, 0, 1]
        return tdmeta

    ######################################################################
    # network and status:
    def server_connection_state_change(self) -> None:
        windows = tuple(getattr(self, "_id_to_window", {}).values())
        if not windows:
            return
        ok = self._server_ok or FORCE_ALERT
        if ok:
            log.info("server is OK again")
            return
        log.info("server is not responding, drawing alert state over the windows")
        self.schedule_timer_redraw()

    def schedule_timer_redraw(self) -> None:
        log("schedule_timer_redraw()")

        def timer_redraw() -> bool:
            if self._protocol is None:
                # no longer connected!
                return False
            ok = self._server_ok and not FORCE_ALERT
            log("timer_redraw() ok=%s", ok)
            # ensure every window has the latest state:
            for window in self._id_to_window.values():
                if not window.is_tray():
                    window.set_alert_state(not ok)
            self.redraw_windows()
            return not ok  # repaint again until ok

        GLib.idle_add(self.redraw_windows)
        GLib.timeout_add(100, timer_redraw)

    def redraw_windows(self) -> None:
        # redraws all the windows without requesting a refresh from the server:
        for window in self._id_to_window.values():
            window.redraw()

    ######################################################################
    # packets:
    def init_authenticated_packet_handlers(self) -> None:
        log("init_authenticated_packet_handlers()")
        for c in CLIENT_BASES:
            c.init_authenticated_packet_handlers(self)
        # run from the UI thread:
        self.add_packets("startup-complete", "setting-change", main_thread=True)
        # run directly from the network thread:
        self.add_packets("server-event")
