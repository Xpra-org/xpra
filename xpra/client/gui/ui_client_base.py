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
from xpra.client.gui.keyboard_helper import KeyboardHelper
from xpra.platform import set_name
from xpra.platform.gui import ready as gui_ready, get_wm_name, get_session_type, ClientExtras
from xpra.common import FULL_INFO, noop, NotificationID, ConnectionMessage, noerr, get_run_info
from xpra.net.common import PacketType
from xpra.keyboard.common import KeyEvent
from xpra.os_util import POSIX, WIN32, OSX, gi_import
from xpra.util.child_reaper import reaper_cleanup
from xpra.util.version import get_platform_info
from xpra.util.system import is_Wayland, platform_name
from xpra.util.objects import typedict
from xpra.util.screen import log_screen_sizes
from xpra.util.str_fn import std, Ellipsizer, repr_ellipsized
from xpra.util.env import envint, envbool
from xpra.scripts.config import str_to_bool
from xpra.exit_codes import ExitCode, ExitValue
from xpra.client.base import features
from xpra.log import Logger

CLIENT_BASES = get_client_base_classes()
ClientBaseClass = type('ClientBaseClass', CLIENT_BASES, {})

GLib = gi_import("GLib")

log = Logger("client")
keylog = Logger("client", "keyboard")
log("UIXpraClient%s: %s", ClientBaseClass, CLIENT_BASES)

NOTIFICATION_EXIT_DELAY = envint("XPRA_NOTIFICATION_EXIT_DELAY", 2)
MOUSE_DELAY_AUTO = envbool("XPRA_MOUSE_DELAY_AUTO", True)
DELAY_KEYBOARD_DATA = envbool("XPRA_DELAY_KEYBOARD_DATA", True)


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

        self.server_platform: str = ""
        self.server_session_name: str = ""

        # features:
        self.opengl_enabled: bool = False
        self.opengl_props: dict[str, Any] = {}
        self.readonly: bool = False
        self.xsettings_enabled: bool = False
        self.server_start_new_commands: bool = False
        self.server_xdg_menu = None
        self.start_new_commands: bool = False
        self.request_start = []
        self.request_start_child = []
        self.headerbar = None
        self.suspended = False

        # in WindowClient - should it be?
        # self.server_is_desktop = False
        self.server_sharing: bool = False
        self.server_sharing_toggle: bool = False
        self.server_lock: bool = False
        self.server_lock_toggle: bool = False
        self.server_keyboard: bool = True
        self.server_pointer: bool = True
        self.server_commands_info = False
        self.server_commands_signals: Sequence[str] = ()
        self.server_readonly = False
        self.server_setting_updates: dict[str, Any] = {}

        self.client_supports_opengl: bool = False
        self.client_supports_sharing: bool = False
        self.client_lock: bool = False

        # helpers and associated flags:
        self.client_extras = None
        self._mouse_position_delay = 5
        self.keyboard_helper_class: type = KeyboardHelper
        self.keyboard_helper = None
        self.keyboard_grabbed: bool = False
        self.keyboard_sync: bool = False
        self.key_repeat_delay = -1
        self.key_repeat_interval = -1
        self.kh_warning: bool = False
        self.menu_helper = None

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
        self.xsettings_enabled = not (OSX or WIN32) and str_to_bool(opts.xsettings)
        self.readonly = opts.readonly
        self.client_supports_sharing = opts.sharing is True
        self.client_lock = opts.lock is True
        self.headerbar = opts.headerbar

    def client_toolkit(self) -> str:
        raise NotImplementedError()

    def init_ui(self, opts) -> None:
        """ initialize user interface """

        def noauto(val) -> str | Sequence | None:
            default = [] if isinstance(val, Sequence) else None
            if not val:
                return default
            if str(val).lower() == "auto":
                return default
            return val

        send_keyboard = noop
        if not self.readonly:
            def do_send_keyboard(*parts):
                self.after_handshake(self.send, *parts)

            send_keyboard = do_send_keyboard
        try:
            kwargs = dict(
                (x, noauto(getattr(opts, "keyboard_%s" % x))) for x in (
                    "backend", "model", "layout", "layouts", "variant", "variants", "options",
                )
            )
            self.keyboard_helper = self.keyboard_helper_class(send_keyboard, opts.keyboard_sync,
                                                              opts.shortcut_modifiers,
                                                              opts.key_shortcut,
                                                              opts.keyboard_raw, **kwargs)
            if DELAY_KEYBOARD_DATA and not self.readonly:
                self.after_handshake(self.keyboard_helper.send_keymap)
        except ImportError as e:
            keylog("error instantiating %s", self.keyboard_helper_class, exc_info=True)
            keylog.warn(f"Warning: no keyboard support, {e}")

        if features.windows:
            self.init_opengl(opts.opengl)

        if ClientExtras is not None:
            self.client_extras = ClientExtras(self, opts)  # pylint: disable=not-callable

        self.start_new_commands = str_to_bool(opts.start_new_commands)
        if self.start_new_commands and (opts.start or opts.start_child):
            from xpra.scripts.main import strip_defaults_start_child
            from xpra.scripts.config import make_defaults_struct
            defaults = make_defaults_struct()
            self.request_start = strip_defaults_start_child(opts.start, defaults.start)
            self.request_start_child = strip_defaults_start_child(opts.start_child, defaults.start_child)

        if MOUSE_DELAY_AUTO:
            try:
                # some platforms don't detect the vrefresh correctly
                # (ie: macos in virtualbox?), so use a sane default minimum
                # discount by 5ms to ensure we have time to hit the target
                v = max(60, self.get_vrefresh())
                self._mouse_position_delay = max(5, 1000 // v // 2 - 5)
                log(f"mouse position delay: {self._mouse_position_delay}")
            except (AttributeError, OSError):
                log("failed to calculate automatic delay", exc_info=True)

    def get_vrefresh(self) -> int:
        # this method is overridden in the GTK client
        from xpra.platform.gui import get_vrefresh  # pylint: disable=import-outside-toplevel
        return get_vrefresh()

    def run(self) -> ExitValue:
        if self.client_extras:
            GLib.idle_add(self.client_extras.ready)
        for c in CLIENT_BASES:
            c.run(self)
        return self.exit_code or 0

    def quit(self, exit_code: ExitValue = 0) -> None:
        raise NotImplementedError()

    def cleanup(self) -> None:
        log("UIXpraClient.cleanup()")
        for c in CLIENT_BASES:
            c.cleanup(self)
        for x in (self.keyboard_helper, self.tray, self.menu_helper, self.client_extras):
            if x is None:
                continue
            log(f"UIXpraClient.cleanup() calling {type(x)}.cleanup()")
            with log.trap_error(f"Error on {type(x)} cleanup"):
                x.cleanup()
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

    def init_opengl(self, _enable_opengl) -> None:
        self.opengl_enabled = False
        self.client_supports_opengl = False
        self.opengl_props = {"info": "not supported"}

    def _ui_event(self) -> None:
        if self._ui_events == 0:
            self.emit("first-ui-received")
        self._ui_events += 1

    def get_mouse_position(self):
        raise NotImplementedError()

    def get_current_modifiers(self):
        raise NotImplementedError()

    def send_start_new_commands(self) -> None:
        log(f"send_start_new_commands() {self.request_start=}, {self.request_start_child=}")
        import shlex
        for cmd in self.request_start:
            cmd_parts = shlex.split(cmd)
            self.send_start_command(cmd_parts[0], cmd_parts, True)
        for cmd in self.request_start_child:
            cmd_parts = shlex.split(cmd)
            self.send_start_command(cmd_parts[0], cmd_parts, False)

    def send_start_command(self, name: str, command: list[str], ignore: bool, sharing: bool = True) -> None:
        log("send_start_command%s", (name, command, ignore, sharing))
        assert name is not None and command is not None and ignore is not None
        self.send("start-command", name, command, ignore, sharing)

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
            delay = NOTIFICATION_EXIT_DELAY * int(features.notifications)
            GLib.timeout_add(delay * 1000, XpraClientBase.server_disconnect_warning, self, title, *info)
        self.cleanup()

    def server_disconnect(self, reason: str, *info) -> None:
        body = "\n".join(info)
        self.may_notify(NotificationID.DISCONNECT,
                        f"Xpra Session Disconnected: {reason}", body, icon_name="disconnected")
        delay = NOTIFICATION_EXIT_DELAY * int(features.notifications)
        if self.exit_code is None:
            self.exit_code = self.server_disconnect_exit_code(reason, *info)
        GLib.timeout_add(delay * 1000, XpraClientBase.server_disconnect, self, reason, *info)
        self.cleanup()

    ######################################################################
    # hello:
    def make_hello(self) -> dict[str, Any]:
        caps = XpraClientBase.make_hello(self)
        # don't try to find the server uuid if this platform cannot run servers..
        # (doing so causes lockups on win32 and startup errors on osx)
        if POSIX and not (OSX or is_Wayland()):
            # we may be running inside another server!
            try:
                from xpra.x11.server.server_uuid import get_uuid, get_mode  # pylint: disable=import-outside-toplevel
                if get_mode() != "shadow":
                    uuid = get_uuid()
                    if uuid:
                        caps["server_uuid"] = uuid
            except (ImportError, RuntimeError):
                log("skipped server uuid lookup", exc_info=True)
        for x in (  # generic feature flags:
                "xdg-menu-update",
                "setting-change", "mouse",
        ):
            caps[x] = True
        caps.setdefault("wants", []).append("events")
        caps |= {
            # generic server flags:
            "share": self.client_supports_sharing,
            "lock": self.client_lock,
            "xdg-menu": self.start_new_commands,
        }
        caps.update(self.get_keyboard_caps())
        for c in CLIENT_BASES:
            caps.update(c.get_caps(self))
        if FULL_INFO > 0:
            def skipkeys(d, *keys):
                return {k: v for k, v in d.items() if k not in keys}

            pi = get_platform_info()
            op = self.opengl_props
            if FULL_INFO == 1:
                op = skipkeys(op, "extensions", "GLU.extensions")
                pi = skipkeys(pi, "release", "sysrelease", "platform", "processor", "architecture")
            caps["platform"] = pi
            caps["opengl"] = op
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
        self.add_control_commands()
        return True

    def parse_server_capabilities(self, c: typedict) -> bool:
        for cb in CLIENT_BASES:
            log("%s.parse_server_capabilities(..)", cb)
            try:
                if not cb.parse_server_capabilities(self, c):
                    log.info(f"failed to parse server capabilities in {cb}")
                    return False
            except Exception as e:
                log("%s.parse_server_capabilities(%s)", cb, Ellipsizer(c), exc_info=True)
                log.error("Error parsing server capabilities using %s: %s", cb, e)
                return False
        self.server_session_name = c.strget("session_name")
        set_name("Xpra", self.session_name or self.server_session_name or "Xpra")
        self.server_platform = c.strget("platform")
        self.server_sharing = c.boolget("sharing")
        self.server_sharing_toggle = c.boolget("sharing-toggle")
        self.server_lock = c.boolget("lock")
        self.server_lock_toggle = c.boolget("lock-toggle")
        self.server_keyboard = c.boolget("keyboard", True)
        self.server_pointer = c.boolget("pointer", True)
        self.server_start_new_commands = c.boolget("start-new-commands")
        if self.server_start_new_commands:
            self.server_xdg_menu = c.dictget("xdg-menu", None)
        if self.request_start or self.request_start_child:
            if self.server_start_new_commands:
                self.after_handshake(self.send_start_new_commands)
            else:
                log.warn("Warning: cannot start new commands")
                log.warn(" the feature is currently disabled on the server")
        self.server_commands_info = c.boolget("server-commands-info")
        self.server_commands_signals = c.strtupleget("server-commands-signals")
        self.server_readonly = c.boolget("readonly")
        if self.server_readonly and not self.readonly:
            log.info("server is read only")
            self.readonly = True
        if not self.server_keyboard and self.keyboard_helper:
            # swallow packets:
            self.keyboard_helper.send = noop

        i = platform_name(self._remote_platform,
                          c.strtupleget("platform.linux_distribution") or c.strget("platform.release"))
        r = ".".join(str(x) for x in self._remote_version)
        if self._remote_revision:
            r += f"-r{self._remote_revision}"
        mode = c.strget("server.mode", "server")
        bits = c.intget("python.bits", 0)
        bitsstr = "" if bits == 0 else f" {bits}-bit"
        log.info(f"Xpra {mode} server version {std(r)}{bitsstr}")
        if i and i != "unknown":
            log.info(f" running on {std(i)}")
        if c.boolget("desktop") or c.boolget("shadow"):
            v = c.intpair("actual_desktop_size")
            if v:
                w, h = v
                ss = c.tupleget("screen_sizes")
                log.info(f" remote desktop size is {w}x{h}")
                if ss:
                    log_screen_sizes(w, h, ss)
        proxy = c.get("proxy")
        if proxy:
            if isinstance(proxy, dict):
                pcaps = typedict(proxy)
                prefix = ""
            else:
                pcaps = c
                prefix = "proxy."
            proxy_hostname = pcaps.strget(f"{prefix}hostname")
            proxy_platform = pcaps.strget(f"{prefix}platform")
            proxy_release = pcaps.strget(f"{prefix}platform.release")
            proxy_version = pcaps.strget(f"{prefix}version")
            proxy_version = pcaps.strget(f"{prefix}build.version", proxy_version)
            proxy_distro = pcaps.strget(f"{prefix}linux_distribution")
            msg = "via: %s proxy version %s" % (
                platform_name(proxy_platform, proxy_distro or proxy_release),
                std(proxy_version or "unknown")
            )
            if proxy_hostname:
                msg += " on '%s'" % std(proxy_hostname)
            log.info(msg)
        return True

    def process_ui_capabilities(self, caps: typedict) -> None:
        for c in CLIENT_BASES:
            if c != XpraClientBase:
                c.process_ui_capabilities(self, caps)
        # keyboard:
        if self.keyboard_helper:
            modifier_keycodes = caps.dictget("modifier_keycodes", {})
            if modifier_keycodes:
                self.keyboard_helper.set_modifier_mappings(modifier_keycodes)
        self.key_repeat_delay, self.key_repeat_interval = caps.intpair("key_repeat", (-1, -1))
        self.handshake_complete()

    def _process_startup_complete(self, packet: PacketType) -> None:
        log("all the existing windows and system trays have been received")
        super()._process_startup_complete(packet)
        gui_ready()
        if self.tray:
            self.tray.ready()
        self.send_info_request()
        msg = "running"
        try:
            windows = tuple(self._id_to_window.values())
        except AttributeError:
            pass
        else:
            trays = sum(1 for w in windows if w.is_tray())
            wins = sum(1 for w in windows if not w.is_tray())
            if wins:
                msg += f", {wins} windows"
            if trays:
                msg += f", {trays} tray"
        log.info(msg)

    def _process_new_window(self, packet: PacketType):
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
    def _process_server_event(self, packet: PacketType) -> None:
        log(": ".join(str(x) for x in packet[1:]))

    def on_server_setting_changed(self, setting: str, cb: Callable[[str, Any], None]) -> None:
        self._on_server_setting_changed.setdefault(setting, []).append(cb)
        # has the value already been updated:
        value = self.server_setting_updates.get(setting)
        log("on_server_setting_changed%s value=%s", (setting, cb), value)
        if value is not None:
            cb(setting, value)

    def _process_setting_change(self, packet: PacketType) -> None:
        setting = str(packet[1])
        value = packet[2]
        # convert "hello" / "setting" variable names to client variables:
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
                "xdg-menu", "monitors",
                "ibus-layouts",
        ):
            setattr(self, "server_%s" % setting.replace("-", "_"), value)
        else:
            log.info("unknown server setting changed: %s=%s", setting, repr_ellipsized(value))
            return
        log("_process_setting_change: %s=%s", setting, Ellipsizer(value))
        # these are too big to log
        if setting not in ("xdg-menu", "monitors", "ibus-layouts"):
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
        self.send("set-cursors", self.cursors_enabled)

    def send_force_ungrab(self, wid: int) -> None:
        self.send("force-ungrab", wid)

    def send_keyboard_sync_enabled_status(self, *_args) -> None:
        self.send("set-keyboard-sync-enabled", self.keyboard_sync)

    ######################################################################
    # keyboard:
    def get_keyboard_caps(self) -> dict[str, Any]:
        caps = {}
        kh = self.keyboard_helper
        if self.readonly or not kh:
            # don't bother sending keyboard info, as it won't be used
            caps["keyboard"] = False
        else:
            caps["keyboard"] = True
            caps["ibus"] = True
            caps["modifiers"] = self.get_current_modifiers()
            skip = ("keycodes", "x11_keycodes") if DELAY_KEYBOARD_DATA else ()
            caps["keymap"] = kh.get_keymap_properties(skip)
            # show the user a summary of what we have detected:
            self.keyboard_helper.log_keyboard_info()
            delay_ms, interval_ms = kh.key_repeat_delay, kh.key_repeat_interval
            if delay_ms > 0 and interval_ms > 0:
                caps["key_repeat"] = (delay_ms, interval_ms)
            else:
                # cannot do keyboard_sync without a key repeat value!
                # (maybe we could just choose one?)
                kh.keyboard_sync = False
            caps["keyboard_sync"] = kh.sync
        log("keyboard capabilities: %s", caps)
        return caps

    def next_keyboard_layout(self, update_platform_layout) -> None:
        if self.keyboard_helper:
            self.keyboard_helper.next_layout(update_platform_layout)

    def window_keyboard_layout_changed(self, window=None) -> None:
        # win32 can change the keyboard mapping per window...
        keylog("window_keyboard_layout_changed(%s)", window)
        if self.keyboard_helper:
            self.keyboard_helper.keymap_changed()

    def handle_key_action(self, window, key_event: KeyEvent) -> bool:
        kh = self.keyboard_helper
        if not kh:
            return False
        wid = self._window_to_id[window]
        keylog(f"handle_key_action({window}, {key_event}) wid={wid}")
        if kh.key_handled_as_shortcut(window, key_event.keyname, key_event.modifiers, key_event.pressed):
            return False
        if self.readonly:
            return False
        kh.process_key_event(wid, key_event)
        return False

    def mask_to_names(self, mask) -> list[str]:
        if self.keyboard_helper is None:
            return []
        return self.keyboard_helper.mask_to_names(int(mask))

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
        if not self._server_ok and hasattr(self, "redraw_spinners"):
            log.info("server is not responding, drawing spinners over the windows")

            def timer_redraw() -> bool:
                if self._protocol is None:
                    # no longer connected!
                    return False
                ok = self.server_ok()
                self.redraw_spinners()
                if ok:
                    log.info("server is OK again")
                return not ok  # repaint again until ok

            GLib.idle_add(self.redraw_spinners)
            GLib.timeout_add(250, timer_redraw)

    ######################################################################
    # packets:
    def init_authenticated_packet_handlers(self) -> None:
        log("init_authenticated_packet_handlers()")
        for c in CLIENT_BASES:
            c.init_authenticated_packet_handlers(self)
        # run from the UI thread:
        self.add_packets("startup-complete", "setting-change", "control", main_thread=True)
        # run directly from the network thread:
        self.add_packets("server-event")

    def process_packet(self, proto, packet) -> None:
        self.check_server_echo(0)
        super().process_packet(proto, packet)
