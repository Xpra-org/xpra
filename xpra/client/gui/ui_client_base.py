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
from xpra.common import noerr, may_notify_client
from xpra.net.constants import ConnectionMessage
from xpra.constants import NotificationID
from xpra.net.common import Packet, print_proxy_caps, FULL_INFO, BACKWARDS_COMPATIBLE
from xpra.net.packet_type import CURSOR_SET, KEYBOARD_SYNC, NOTIFICATION_STATUS
from xpra.util.child_reaper import reaper_cleanup
from xpra.util.objects import typedict
from xpra.util.system import get_run_info
from xpra.util.str_fn import Ellipsizer, repr_ellipsized
from xpra.util.env import envint, envbool
from xpra.exit_codes import ExitCode, ExitValue
from xpra.client.base import features
from xpra.log import Logger

CLIENT_BASES = get_client_base_classes()
# Composed subsystems live as separate instances in `client.subsystems` (reached via
# `get_subsystem(...)`), so they are kept OUT of the client's MRO. `UIXpraClient` only
# inherits from `XpraClientBase` plus the subsystems still muxed into the client object
# (currently just `native`/`PlatformClient`; the `base/*` transport mixins go with Phase 3).
# The full `CLIENT_BASES` list is still used to drive lifecycle/caps/signal dispatch below.
MUXED_BASES = tuple(c for c in CLIENT_BASES if getattr(c, "PREFIX", "") not in XpraClientBase.COMPOSED_SUBSYSTEMS)
ClientBaseClass = type('ClientBaseClass', MUXED_BASES, {})

log = Logger("client")
sublog = Logger("subsystems")
sublog("UIXpraClient base classes: %s (muxed into the MRO: %s)", CLIENT_BASES, MUXED_BASES)

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
    # these are all "no-arg" signals.
    # composed subsystems own and declare their own signals now (see their
    # `__signals__`) and are not aggregated here - `SignalEmitter` warns if a
    # signal used with `emit`/`connect` isn't in the emitter's own list.
    __signals__ = ["first-ui-received"] + XpraClientBase.__signals__

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
        # the menu helper is a client-owned UI service (used by the `tray`
        # subsystem and by window shortcut menus); toolkit clients override
        # `get_menu_helper`/`get_menu_helper_class` to add their variants:
        self.menu_helper = None
        for c in CLIENT_BASES:
            sublog("calling %s.__init__()", c)
            self.add_subsystem(c)
        # react to the `ping` subsystem's "timeout" signal by drawing an alert
        # state over the windows (a UI concern, so it lives here, not in `ping`):
        if ping := self.get_subsystem("ping"):
            ping.connect("timeout", self.server_connection_state_change)
        self._ui_events: int = 0
        self.title: str = ""
        self.session_name: str = ""
        self.server_session_name: str = ""

        # features:
        self.readonly: bool = False
        self.headerbar = None
        # `suspended` is owned by the `power` subsystem,
        # `server_pointer` by the `pointer` subsystem,
        # `server_is_desktop` by the `display` subsystem
        self.server_sharing: bool = False
        self.server_sharing_toggle: bool = False
        self.server_lock: bool = False
        self.server_lock_toggle: bool = False
        self.server_readonly = False
        self.server_setting_updates: dict[str, Any] = {}

        self.client_supports_sharing: bool = False
        self.client_lock: bool = False

        # state:
        self._on_server_setting_changed: dict[str, Sequence[Callable[[str, Any], None]]] = {}

    def init(self, opts) -> None:
        """ initialize variables from configuration """
        for c in CLIENT_BASES:
            sublog(f"init: {c}")
            self._call_subsystem(c, "init", opts)

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
            sublog(f"init: {c}")
            self._call_subsystem(c, "init_ui", opts)

    def load(self):
        for c in CLIENT_BASES:
            sublog(f"load: {c}")
            self._call_subsystem(c, "load")

    def run(self) -> ExitValue:
        if FORCE_ALERT:
            self.schedule_timer_redraw()
        for c in CLIENT_BASES:
            self._call_subsystem(c, "run")
        return self.exit_code or 0

    def quit(self, exit_code: ExitValue = 0) -> None:
        raise NotImplementedError()

    def cleanup(self) -> None:
        log("UIXpraClient.cleanup()")
        for c in CLIENT_BASES:
            sublog("%s.cleanup()", c)
            self._call_subsystem(c, "cleanup")
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
            with sublog.trap_error("Error collection information from %s", c):
                info.update(self._call_subsystem(c, "get_info"))
        return info

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

    def get_notifier_classes(self) -> Sequence[Callable]:
        # the canonical notifier list lives on the client: concrete clients
        # (e.g. gtk3) override this to add their toolkit-specific notifiers on
        # top of the notification subsystem's native ones. This base default
        # exposes just the native classes (for clients with no toolkit variants).
        notification = self.get_subsystem("notification")
        return list(notification.get_native_notifier_classes()) if notification else []

    def get_gl_client_window_module(self, _enable_opengl: str) -> tuple[dict, Any]:
        # the (toolkit-specific) OpenGL window backend, asked for by the `display`
        # subsystem's `init_opengl`. No backend by default; toolkits that support
        # OpenGL rendering (e.g. gtk3) override this.
        return {}, None

    def get_menu_helper(self):
        """
        menu helper used by our tray (make_tray / setup_xpra_tray)
        and for showing the menu on windows via a shortcut;
        concrete clients (e.g. gtk3) override this to add toolkit variants.
        """
        if not self.menu_helper:
            from xpra.util.objects import make_instance
            mhc = (self.get_menu_helper_class(), )
            log("get_menu_helper() menu helper classes: %s", mhc)
            self.menu_helper = make_instance(mhc, self)
        return self.menu_helper

    @staticmethod
    def get_menu_helper_class():
        from xpra.platform.systray import get_menu_helper_class
        return get_menu_helper_class()

    def show_menu(self, *_args) -> None:
        if self.menu_helper:
            self.menu_helper.activate()

    def get_tray_classes(self) -> list[type]:
        # the canonical tray class list lives on the client: concrete clients
        # (e.g. gtk3) override this to add their toolkit-specific trays on top
        # of the tray subsystem's native ones.
        tray = self.get_subsystem("tray")
        return list(tray.get_native_tray_classes()) if tray else []

    def server_ok(self) -> bool:
        # get the real value from the PingClient feature, if present:
        ping = self.get_subsystem("ping")
        return ping._server_ok if ping else True

    def get_windows(self) -> tuple:
        """ all the windows currently registered with the `window` subsystem """
        window = self.get_subsystem("window")
        return tuple(window._id_to_window.values()) if window else ()

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
            may_notify_client(self, NotificationID.DISCONNECT, title, body, icon_name="disconnected")
            # show text notification then quit:
            delay = NOTIFICATION_EXIT_DELAY * int(features.notification)
            self.timeout_add(delay * 1000, XpraClientBase.server_disconnect_warning, self, title, *info)
        self.cleanup()

    def server_disconnect(self, reason: str, *info) -> None:
        body = "\n".join(info)
        may_notify_client(self, NotificationID.DISCONNECT,
                          f"Xpra Session Disconnected: {reason}", body, icon_name="disconnected")
        delay = NOTIFICATION_EXIT_DELAY * int(features.notification)
        if self.exit_code is None:
            self.exit_code = self.server_disconnect_exit_code(reason, *info)
        self.timeout_add(delay * 1000, XpraClientBase.server_disconnect, self, reason, *info)
        self.cleanup()

    ######################################################################
    # hello:
    def make_hello(self) -> dict[str, Any]:
        caps = XpraClientBase.make_hello(self)
        if BACKWARDS_COMPATIBLE:
            caps.setdefault("wants", []).append("events")
        caps |= {
            "setting-change": True,
            "server-features": True,
            "versions": True,
            # generic server flags:
            "readonly": self.readonly,
            "share": self.client_supports_sharing,
            "lock": self.client_lock,
        }
        for c in CLIENT_BASES:
            ccaps = self._call_subsystem(c, "get_caps")
            sublog("%s.get_caps()=%s", c, ccaps)
            caps.update(ccaps)
        if FULL_INFO > 0:
            caps["session-type"] = get_session_type()
        return caps

    ######################################################################
    # connection setup:
    def setup_connection(self, conn) -> None:
        for c in CLIENT_BASES:
            self._call_subsystem(c, "setup_connection", conn)

    def parse_server_capabilities(self, c: typedict) -> bool:
        for cb in CLIENT_BASES:
            sublog("%s.parse_server_capabilities(..)", cb)
            try:
                if not self._call_subsystem(cb, "parse_server_capabilities", c):
                    sublog.info(f"failed to parse server capabilities in {cb}")
                    return False
            except Exception:
                sublog("%s.parse_server_capabilities(%s)", cb, Ellipsizer(c))
                sublog.error("Error parsing server capabilities using %s", cb, exc_info=True)
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

    def connection_accepted(self, caps: typedict) -> None:
        """ overriden here so we can call `handshake_complete` from the main thread """
        log("connection accepted caps=%s", Ellipsizer(caps))
        self.connection_established = True
        self.idle_add(self.handshake_complete)

    def _process_startup_complete(self, packet: Packet) -> None:
        log("all the existing windows and system trays have been received")
        super()._process_startup_complete(packet)
        gui_ready()

    def send_hello(self, challenge_response=b"", client_salt=b"") -> None:
        self.idle_add(super().send_hello, challenge_response, client_salt)

    ######################################################################
    # server messages:
    # noinspection PyMethodMayBeStatic

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
                "readonly",
                "start-new-commands", "client-shutdown", "webcam",
                "bandwidth-limit", "clipboard-limits",
                "menu", "monitors",
                "ibus-layouts",
        ):
            setattr(self, "server_%s" % setting.replace("-", "_"), value)
            if setting == "readonly" and value:
                self.readonly = True
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
        # called by the `control` subsystem (it owns the base commands; this
        # adds the UI-specific ones on top, via the `add_control_command` delegate
        # since this class and the `control` subsystem are no longer related by
        # inheritance - see `ControlClient.parse_server_capabilities`):
        try:
            from xpra.net.control.common import ControlCommand, ArgsControlCommand
        except ImportError as e:
            log(f"control commands are not available: {e}")
            return
        self.add_control_command(
            "show_session_info", ControlCommand("show-session-info", "Shows the session info dialog", self.show_session_info))
        self.add_control_command(
            "show_bug_report", ControlCommand("show-bug-report", "Shows the bug report dialog", self.show_bug_report))
        self.add_control_command(
            "name", ArgsControlCommand("name", "Sets the server session name", self.set_server_session_name,
                                       min_args=1, max_args=1))

    def set_server_session_name(self, name: str):
        self.server_session_name = name
        log.info("session name updated from server: %s", self.server_session_name)

    ######################################################################
    # features:
    def send_sharing_enabled(self) -> None:
        assert self.server_sharing and self.server_sharing_toggle
        self.send("sharing-toggle", self.client_supports_sharing)

    def send_lock_enabled(self) -> None:
        assert self.server_lock_toggle
        self.send("lock-toggle", self.client_lock)

    def send_notify_enabled(self) -> None:
        notification = self.get_subsystem("notification")
        assert notification.client_supports, "cannot toggle notifications: the feature is disabled by the client"
        self.send(NOTIFICATION_STATUS, notification.enabled)

    def send_cursors_enabled(self) -> None:
        cursor = self.get_subsystem("cursor")
        assert cursor and cursor.client_supports, "cannot toggle cursors: the feature is disabled by the client"
        assert cursor.server_enabled, "cannot toggle cursors: the feature is disabled by the server"
        self.send(CURSOR_SET, cursor.enabled)

    def send_force_ungrab(self, wid: int) -> None:
        self.send("force-ungrab", wid)

    def send_keyboard_sync_enabled_status(self, *_args) -> None:
        if kb := self.get_subsystem("keyboard"):
            self.send(KEYBOARD_SYNC, kb.sync)

    ######################################################################
    # windows overrides
    def cook_metadata(self, _new_window, metadata: dict) -> typedict:
        # convert to a typedict and apply client-side overrides:
        tdmeta = typedict(metadata)
        display = self.get_subsystem("display")
        if display and display.server_is_desktop and display.desktop_fullscreen:
            # force it fullscreen:
            metadata.pop("size-constraints", None)
            metadata["fullscreen"] = True
            # FIXME: try to figure out the monitors we go fullscreen on for X11:
            # if POSIX:
            #    metadata["fullscreen-monitors"] = [0, 1, 0, 1]
        return tdmeta

    ######################################################################
    # network and status:
    def server_connection_state_change(self, *_args) -> None:
        # handler for the `ping` subsystem's "timeout" signal (see `__init__`):
        windows = self.get_windows()
        if not windows:
            return
        if self.server_ok() or FORCE_ALERT:
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
            ok = self.server_ok() and not FORCE_ALERT
            log("timer_redraw() ok=%s", ok)
            # ensure every window has the latest state:
            for window in self.get_windows():
                if not window.is_tray():
                    window.set_alert_state(not ok)
            self.redraw_windows()
            return not ok  # repaint again until ok

        self.idle_add(self.redraw_windows)
        self.timeout_add(100, timer_redraw)

    def redraw_windows(self) -> None:
        # redraws all the windows without requesting a refresh from the server:
        for window in self.get_windows():
            window.redraw()

    ######################################################################
    # packets:
    def init_authenticated_packet_handlers(self) -> None:
        log("init_authenticated_packet_handlers()")
        for c in CLIENT_BASES:
            self._call_subsystem(c, "init_authenticated_packet_handlers")
        # run from the UI thread:
        self.add_packets("startup-complete", "setting-change", main_thread=True)
