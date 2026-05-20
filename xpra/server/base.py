# This file is part of Xpra.
# Copyright (C) 2011 Serviware (Arthur Huillet, <ahuillet@serviware.com>)
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from collections.abc import Sequence
from time import monotonic
from typing import Any

from xpra.server.common import get_sources_by_type
from xpra.server.core import ServerCore, SIGNALS as CORE_SIGNALS
from xpra.server.source.events import EventConnection
from xpra.util.background_worker import add_work_item
from xpra.common import noop
from xpra.net.constants import ConnectionMessage
from xpra.net.common import Packet, PacketElement, FULL_INFO, BACKWARDS_COMPATIBLE
from xpra.os_util import gi_import
from xpra.util.objects import typedict, merge_dicts
from xpra.util.str_fn import Ellipsizer
from xpra.util.env import envbool
from xpra.server import ServerExitMode
from xpra.os_util import POSIX
from xpra.server.factory import get_server_base_classes
from xpra.log import Logger

GLib = gi_import("GLib")

log = Logger("server")
netlog = Logger("network")
authlog = Logger("auth")
eventslog = Logger("events")

SERVER_BASES = get_server_base_classes()
SIGNALS: dict[str, int] = {
    **CORE_SIGNALS,
    "last-client-exited": 0,
    "client-exited": 1,
    "new-ui-driver": 1,
}
ServerBaseClass = type("ServerBaseClass", SERVER_BASES, {})
log("ServerBaseClass%s", SERVER_BASES)
log("signals: %s", SIGNALS)

CLIENT_CAN_SHUTDOWN = envbool("XPRA_CLIENT_CAN_SHUTDOWN", True)


class ServerBase(ServerBaseClass):
    """
    This is the base class for seamless and desktop servers. (not proxy servers)
    It provides all the generic functions but is not tied
    to a specific backend (X11 or otherwise).
    See X11ServerBase and other platform specific subclasses.
    """
    toggle_features = ("client-shutdown",)
    __signals__ = SIGNALS
    # ServerBase is the framework, not a subsystem.
    # Explicitly clear PREFIX so it isn't picked up by getattr() through the
    # dynamic ServerBaseClass MRO (which inherits PREFIX from its subsystems):
    PREFIX = ""

    def __init__(self):
        # subsystems dict (keyed by PREFIX) is built up across the inheritance
        # hierarchy: ServerCore.__init__ adds its own bases, and this loop adds
        # all the extra subsystems from factory.SERVER_BASES on top.
        if not hasattr(self, "subsystems"):
            self.subsystems: dict = {}
        for c in SERVER_BASES:
            # legacy mixin subsystems share `self` with the server, so we
            # pass `self` as both the bound instance and as the server arg:
            c.__init__(self, self)
            prefix = getattr(c, "PREFIX", "")
            if prefix:
                self.subsystems[prefix] = c
        # Instantiate the standalone instance-based subsystems. Variant
        # servers (seamless, desktop, monitor, shadow, ...) override the
        # `get_*_subsystem_class()` hooks to swap in their own subclasses.
        for cls in self.get_subsystem_classes():
            self.subsystems[cls.PREFIX] = cls(self)
        log("ServerBase.__init__()")
        self.hello_request_handlers.update({
            "exit": self._handle_hello_request_exit,
            "stop": self._handle_hello_request_stop,
        })
        self._server_sources: dict = {}
        self.ui_driver = None
        self.client_shutdown: bool = CLIENT_CAN_SHUTDOWN

    def get_subsystem_classes(self) -> tuple[type, ...]:
        """
        Return the ordered tuple of instance-based subsystem classes to
        construct for this server. Variants (seamless, desktop, monitor,
        shadow, ...) override the per-subsystem hooks below (display,
        window, keyboard, pointer) to swap in their own subclasses.
        """
        from xpra.server import features
        classes: list[type] = []
        if features.gtk:
            if features.x11:
                from xpra.x11.subsystem.gtk import GtkX11Server
                classes.append(GtkX11Server)
            else:
                from xpra.server.subsystem.gtk import GTKServer
                classes.append(GTKServer)
        elif features.x11:
            from xpra.x11.subsystem.x11init import X11Init
            classes.append(X11Init)
        if features.ping:
            from xpra.server.subsystem.ping import PingServer
            classes.append(PingServer)
        if features.bandwidth:
            from xpra.server.subsystem.bandwidth import BandwidthServer
            classes.append(BandwidthServer)
        if features.debug:
            from xpra.server.subsystem.debug import DebugServer
            classes.append(DebugServer)
        if features.shell:
            from xpra.server.subsystem.shell import ShellServer
            classes.append(ShellServer)
        if features.power:
            from xpra.server.subsystem.power import PowerEventServer
            classes.append(PowerEventServer)
        if features.watcher:
            from xpra.server.subsystem.watcher import UIWatcher
            classes.append(UIWatcher)
        if features.suspend:
            from xpra.server.subsystem.suspend import SuspendServer
            classes.append(SuspendServer)
        if features.idle:
            from xpra.server.subsystem.idle import IdleTimeoutServer
            classes.append(IdleTimeoutServer)
        if POSIX and FULL_INFO >= 1:
            from xpra.server.subsystem.drm import DRMInfo
            classes.append(DRMInfo)
        if features.http:
            from xpra.server.subsystem.http import HttpServer
            classes.append(HttpServer)
        if features.ssh:
            from xpra.server.subsystem.ssh_agent import SshAgent
            classes.append(SshAgent)
        if features.dbus:
            from xpra.server.subsystem.dbus import DbusServer
            classes.append(DbusServer)
        # EncryptionServer is unconditional - it gracefully no-ops when no
        # encryption is configured on a given socket.
        from xpra.server.subsystem.encryption import EncryptionServer
        classes.append(EncryptionServer)
        if features.command:
            from xpra.server.subsystem.menu import MenuServer
            classes.append(MenuServer)
        if features.logging:
            from xpra.server.subsystem.logging import LoggingServer
            classes.append(LoggingServer)
        if features.tray:
            from xpra.server.subsystem.tray import TrayMenu
            classes.append(TrayMenu)
        if features.opengl:
            from xpra.server.subsystem.opengl import OpenGLInfo
            classes.append(OpenGLInfo)
        if features.mmap:
            from xpra.server.subsystem.mmap import MMAP_Server
            classes.append(MMAP_Server)
        if features.notification:
            from xpra.server.subsystem.notification import NotificationForwarder
            classes.append(NotificationForwarder)
        if features.webcam:
            from xpra.server.subsystem.webcam import WebcamServer
            classes.append(WebcamServer)
        if features.clipboard:
            from xpra.server.subsystem.clipboard import ClipboardServer
            classes.append(ClipboardServer)
        if features.pulseaudio:
            from xpra.server.subsystem.pulseaudio import PulseaudioServer
            classes.append(PulseaudioServer)
        if features.audio:
            from xpra.server.subsystem.audio import AudioServer
            classes.append(AudioServer)
        if features.encoding:
            from xpra.server.subsystem.encoding import EncodingServer
            classes.append(EncodingServer)
        if features.display:
            classes.append(self.get_display_subsystem_class())
        if features.window:
            classes.append(self.get_window_subsystem_class())
        if features.keyboard:
            classes.append(self.get_keyboard_subsystem_class())
        if features.pointer:
            classes.append(self.get_pointer_subsystem_class())
        # ChildCommandServer should be last so that the environment is fully prepared:
        if features.command:
            from xpra.server.subsystem.command import ChildCommandServer
            classes.append(ChildCommandServer)
        if features.file:
            from xpra.server.subsystem.file import FileServer
            classes.append(FileServer)
        if features.printer:
            from xpra.server.subsystem.printer import PrinterServer
            classes.append(PrinterServer)
        if features.x11 and features.display:
            from xpra.x11.subsystem.icc import ICCServer
            classes.append(ICCServer)
        if features.x11 and features.bell:
            from xpra.x11.subsystem.bell import BellServer
            classes.append(BellServer)
        if features.x11 and features.systray:
            from xpra.x11.subsystem.systray import SystemTrayServer
            classes.append(SystemTrayServer)
        from xpra.server.subsystem.sharing import SharingServer
        classes.append(SharingServer)
        if features.cursor:
            if features.x11:
                from xpra.x11.subsystem.cursor import XCursorServer
                classes.append(XCursorServer)
            else:
                from xpra.server.subsystem.cursor import CursorManager
                classes.append(CursorManager)
        if features.x11 and features.display:
            from xpra.x11.subsystem.xsettings import XSettingsServer
            classes.append(XSettingsServer)
        return tuple(classes)

    def get_display_subsystem_class(self) -> type:
        from xpra.server import features
        if features.x11:
            from xpra.x11.subsystem.display import X11DisplayManager
            return X11DisplayManager
        from xpra.server.subsystem.display import DisplayManager
        return DisplayManager

    def get_window_subsystem_class(self) -> type:
        from xpra.server.subsystem.window import WindowServer
        return WindowServer

    def get_keyboard_subsystem_class(self) -> type:
        from xpra.server import features
        if features.x11:
            from xpra.x11.subsystem.keyboard import X11KeyboardManager
            return X11KeyboardManager
        from xpra.server.subsystem.keyboard import KeyboardManager
        return KeyboardManager

    def get_pointer_subsystem_class(self) -> type:
        from xpra.server import features
        if features.x11:
            from xpra.x11.subsystem.pointer import X11PointerManager
            return X11PointerManager
        from xpra.server.subsystem.pointer import PointerManager
        return PointerManager

    def suspend_event(self, *_args) -> None:
        # if we get a `suspend_event`, we can assume that `PowerEventServer` is a superclass:
        self.server_event("suspend")
        for s in self.window_sources():
            s.go_idle()

    def resume_event(self, *_args) -> None:
        self.server_event("resume")
        for s in self.window_sources():
            s.no_idle()

    def server_event(self, event_type: str, *args: PacketElement) -> None:
        eventslog("server_event%s", (event_type, *args))
        try:
            event_sources = get_sources_by_type(self, EventConnection)
        except ImportError:
            pass
        else:
            for s in event_sources:
                s.send_server_event(event_type, *args)
        # the dbus subsystem is optional:
        dbus = self.subsystems.get("dbus")
        if dbus and dbus.service:
            dbus.service.Event(event_type, [str(x) for x in args[1:]])

    def get_server_source(self, proto):
        return self._server_sources.get(proto)

    def init(self, opts) -> None:
        # from now on, use the logger for parsing errors:
        from xpra.scripts import config  # pylint: disable=import-outside-toplevel
        config.warn = log.warn
        # ServerCore.init handles connection-layer setup and dispatches `init`
        # to every entry in self.subsystems (which includes both core's bases
        # and the extra subsystems registered by ServerBase.__init__):
        super().init(opts)

    def setup(self) -> None:
        log("starting component init")
        # ServerCore.setup dispatches `setup` to all subsystems:
        super().setup()

    def get_child_env(self) -> dict[str, str]:
        env = super().get_child_env()
        env.update(self._dispatch_merge("get_child_env"))
        return env

    def server_is_ready(self) -> None:
        super().server_is_ready()
        self.server_event("ready")

    def do_cleanup(self) -> None:
        # ServerCore.cleanup has already dispatched `cleanup` to all subsystems
        # before invoking do_cleanup; we just emit the server event here.
        self.server_event("exit")
        log("do_cleanup()")

    def late_cleanup(self, stop=True) -> None:
        # ServerCore.late_cleanup dispatches `late_cleanup` to all subsystems
        # then cleans up potential protocols and the child reaper:
        super().late_cleanup(stop)

    # Display-subsystem hooks that variant servers may override. The
    # DisplayManager subsystem calls these via `self.server.X(...)` so
    # that the variant override fires; the defaults here delegate back
    # to the subsystem (where applicable) or no-op.
    def set_desktop_geometry(self, width: int, height: int) -> None:
        """ optionally overridden by server variants """

    def set_workarea(self, workarea) -> None:
        """ optionally overridden by server variants """

    def calculate_desktops(self) -> None:
        """ optionally overridden by server variants """

    def set_dpi(self, xdpi: int, ydpi: int) -> None:
        """ optionally overridden by server variants """

    def set_screen_size(self, width: int, height: int):
        # default: delegate to the display subsystem's implementation.
        # Variants (e.g. SeamlessServer) override this to add wrapping
        # logic and call `super().set_screen_size(...)` to reach here.
        display = self.subsystems.get("display")
        if display is None:
            return width, height
        return display.set_screen_size(width, height)

    def get_window(self, wid: int):
        # convenience delegate to the window subsystem; returns None when
        # there is no window subsystem (e.g. proxy server) or when no
        # window matches the given id.
        window = self.subsystems.get("window")
        if window is None:
            return None
        return window.get_window(wid)

    def window_sources(self, exclude=None) -> tuple:
        # convenience delegate to the window subsystem; returns an empty
        # tuple when there is no window subsystem.
        window = self.subsystems.get("window")
        if window is None:
            return ()
        return window.window_sources(exclude=exclude)

    ######################################################################
    # override http scripts to expose just the current session / display
    def get_displays(self) -> dict[str, Any]:
        from xpra.scripts.display import get_displays  # pylint: disable=import-outside-toplevel
        return get_displays(self.dotxpra, display_names=(self.get_display_name(), ))

    @staticmethod
    def get_display_name() -> str:
        from xpra.platform.gui import get_display_name
        return get_display_name()

    def get_xpra_sessions(self) -> dict[str, Any]:
        from xpra.scripts.sessions import get_xpra_sessions  # pylint: disable=import-outside-toplevel
        return get_xpra_sessions(self.dotxpra, matching_display=self.get_display_name())

    ######################################################################
    # shutdown / exit commands:
    def _process_exit_server(self, _proto, packet: Packet = Packet("exit-server")) -> None:
        # packet from a client
        reason = ""
        if len(packet) > 1:
            reason = packet.get_str(1)
        self._request_exit(reason)

    def _handle_hello_request_exit(self, _proto, _caps: typedict) -> bool:
        # handle "xpra exit" hello request
        self._request_exit()
        return True

    def _request_exit(self, reason: ConnectionMessage | str = "") -> None:
        message = "Exiting in response to client request"
        if reason:
            message += f": {reason}"
        log.info(message)
        self.cleanup_all_protocols(reason=reason)
        GLib.timeout_add(500, self.clean_quit, ServerExitMode.EXIT)

    def _process_shutdown_server(self, _proto, _packet: Packet = Packet("shutdown-server")) -> None:
        self._request_stop()

    def _handle_hello_request_stop(self, _proto, _caps: typedict) -> bool:
        return self._request_stop()

    def _request_stop(self) -> bool:
        if not self.client_shutdown:
            log.warn("Warning: ignoring shutdown request")
            return False
        log.info("Shutting down in response to client request")
        self.cleanup_all_protocols(reason=ConnectionMessage.SERVER_SHUTDOWN)
        GLib.timeout_add(500, self.clean_quit)
        return True

    ######################################################################
    # handle new connections:

    def hello_oked(self, proto, c: typedict, auth_caps: dict) -> None:
        if self.get_server_source(proto):
            log.warn("Warning: received another 'hello' packet")
            log.warn(" from an existing connection: %s", proto)
            return
        if super().hello_oked(proto, c, auth_caps):
            # has been handled
            return
        if not self.sanity_checks(proto, c):
            log("client failed sanity checks")
            return

        def drop_client(reason="unknown", *args) -> None:
            self.disconnect_client(proto, reason, *args)

        cc_class = self.get_client_connection_class(c)
        ss = cc_class(proto, drop_client, self, self.setting_changed)
        log("process_hello clientconnection=%s", ss)
        try:
            ss.parse_hello(c)
        except Exception:
            # close it already
            ss.close()
            raise
        self._server_sources[proto] = ss
        self.accept_protocol(proto, c)
        # process ui half in ui thread:
        GLib.idle_add(self.process_hello_ui, ss, c, auth_caps)

    def get_sources_by_type(self, atype=object, exclude=None) -> Sequence:
        return tuple(ss for ss in self._server_sources.values() if isinstance(ss, atype) and (exclude is None or ss.uuid != exclude.uuid))

    @staticmethod
    def get_client_connection_class(caps: typedict) -> type:
        # pylint: disable=import-outside-toplevel
        from xpra.server.source.factory import get_client_connection_class
        return get_client_connection_class(caps)

    def process_hello_ui(self, ss, c: typedict, auth_caps: dict) -> None:
        def reject(*args) -> None:
            p = ss.protocol
            if p:
                self.disconnect_client(p, *args)

        def closing() -> None:
            reject(ConnectionMessage.CONNECTION_ERROR, "server is shutting down")

        try:
            if self._closing:
                closing()
                return

            err = self.parse_hello(ss, c)
            if err:
                reject(*err.split(":"))
                return

            # send_hello will take care of sending the current and max screen resolutions
            self.send_hello(ss, auth_caps)

            log.info("Handshake complete; enabling connection")
            self.server_event("handshake-complete")
            self.notify_new_user(ss)

            self.add_new_client(ss, c)
            self.send_initial_data(ss)
            self.client_startup_complete(ss)

            if self._closing:
                closing()
                return
        except Exception:
            # log exception but don't disclose internal details to the client
            log("process_hello_ui%s", (ss, c, auth_caps))
            log.error("Error: processing new connection from %s:", ss.protocol or ss, exc_info=True)
            reject("error accepting new connection")

    def parse_hello(self, ss, c: typedict) -> str | ConnectionMessage:
        return self._dispatch_first_truthy("parse_hello", ss, c) or ""

    def add_new_client(self, ss, c: typedict) -> None:
        self._dispatch_fire("add_new_client", ss, c)

    def notify_new_user(self, ss) -> None:
        if notifications := self.subsystems.get("notifications"):
            notifications.notify_new_user(ss)

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

    def send_initial_data(self, ss) -> None:
        self._dispatch_fire("send_initial_data", ss)

    def client_startup_complete(self, ss) -> None:
        ss.startup_complete()
        self.server_event("startup-complete", ss.uuid)

    def sanity_checks(self, proto, c: typedict) -> bool:
        server_uuid = c.strget("server_uuid")
        if server_uuid:
            if server_uuid == self.subsystems["id"].uuid:
                self.send_disconnect(proto, "cannot connect a client running on the same display"
                                            " that the server it connects to is managing - this would create a loop!")
                return False
            log.warn("Warning: this client is running nested")
            log.warn(f" in the Xpra server session {server_uuid!r}")
        return True

    def update_all_server_settings(self, reset: bool = False) -> None:
        pass  # may be overridden in subclasses (ie: x11 server)

    ######################################################################
    # hello:
    def get_server_features(self, server_source=None) -> dict[str, Any]:
        # these are flags that have been added over time with new versions
        # to expose new server features:
        f: dict[str, Any] = {
            "client-shutdown": self.client_shutdown,
        }
        merge_dicts(f, self._dispatch_merge("get_server_features", server_source))
        return f

    def make_hello(self, source) -> dict[str, Any]:
        # super().make_hello already merges get_caps() across subsystems,
        # so the result is complete:
        capabilities = super().make_hello(source)
        capabilities["server_type"] = "base"
        return capabilities

    def send_hello(self, server_source, server_cipher: dict) -> None:
        capabilities = self.make_hello(server_source)
        if server_cipher:
            capabilities.update(server_cipher)
        server_source.send_hello(capabilities)

    ######################################################################
    # info:
    def get_ui_info(self, proto, **kwargs) -> dict[str, Any]:
        """ info that must be collected from the UI thread
            (ie: things that query the display)
        """
        info: dict[str, Any] = {}
        subsystems = kwargs.get("subsystems", ())
        log("ServerBase.get_ui_info(%s, %s) subsystems=%s", proto, kwargs, subsystems)
        for prefix, sub in self.subsystems.items():
            if subsystems and prefix not in subsystems:
                continue
            with log.trap_error("Error collecting UI info from %s", prefix):
                if isinstance(sub, type):
                    mixin_info = sub.get_ui_info(self, proto, **kwargs)
                else:
                    mixin_info = sub.get_ui_info(proto, **kwargs)
                log("%s.get_ui_info(%s, ..)=%r", prefix, proto, Ellipsizer(mixin_info))
                merge_dicts(info, mixin_info)
        return info

    def get_threaded_info(self, proto, **kwargs) -> dict[str, Any]:
        log("ServerBase.get_threaded_info%s", (proto, kwargs))
        start = monotonic()
        info: dict[str, Any] = ServerCore.get_threaded_info(self, proto, **kwargs)
        subsystems = kwargs.get("subsystems", ())

        def up(prefix, d) -> None:
            merge_dicts(info, {prefix: d})

        for prefix, sub in self.subsystems.items():
            if subsystems and prefix not in subsystems:
                continue
            with log.trap_error(f"Error collecting information from {prefix}"):
                cstart = monotonic()
                if isinstance(sub, type):
                    mixin_info = sub.get_info(self, proto)
                else:
                    mixin_info = sub.get_info(proto)
                log("%s.get_info(%s)=%r", prefix, proto, Ellipsizer(mixin_info))
                merge_dicts(info, mixin_info)
                cend = monotonic()
                log("%s.get_info(%s) took %ims", prefix, proto, int(1000 * (cend - cstart)))

        if not subsystems or "features" in subsystems:
            up("features", self.get_features_info())
        info["subsystems"] = self.get_subsystems()

        sources = tuple(self._server_sources.values())
        client_uuids = kwargs.get("client_uuids", ())
        if client_uuids:
            sources = tuple(ss for ss in sources if ss.uuid in client_uuids)
        log("threaded info sources(%i)=%s", client_uuids, sources)
        info.update(self.get_sources_info(proto, sources))
        log("ServerBase.get_info took %.1fms", 1000.0 * (monotonic() - start))
        return info

    def get_features_info(self) -> dict[str, Any]:
        return {}

    def get_subsystems(self) -> list[str]:
        return list(self.subsystems.keys())

    def get_sources_info(self, proto, server_sources=()) -> dict[str, Any]:
        log("ServerBase.get_source_info%s", (proto, server_sources))
        start = monotonic()
        info: dict[str, Any] = {}

        def up(prefix, d) -> None:
            merge_dicts(info, {prefix: d})

        info["clients"] = {
            "": sum(1 for p in self._server_sources if p != proto),
            "unauthenticated": sum(1 for p in self._potential_protocols
                                   if ((p is not proto) and (p not in self._server_sources))),
        }
        log("unauthenticated protocols:")
        for i, p in enumerate(self._potential_protocols):
            log(f"{i:3} : {p}={p.get_info()}")
        cinfo = {}
        for i, ss in enumerate(server_sources):
            sinfo = ss.get_info()
            sinfo["ui-driver"] = self.ui_driver == ss.uuid
            cinfo[i] = sinfo
        up("client", cinfo)
        log("ServerBase.get_source_info took %ims", (monotonic() - start) * 1000)
        return info

    def _process_server_settings(self, proto, packet: Packet) -> None:
        # only used by x11 servers
        pass

    def setting_changed(self, setting: str, value: Any) -> None:
        """ broadcast a server setting change to all connected clients """
        for ss in tuple(self._server_sources.values()):
            ss.send_setting_change(setting, value)

    ######################################################################
    # client connections:
    def disconnect_all(self) -> None:
        protocols = self.get_all_protocols()
        log("disconnect_all() all protocols=%s", protocols)
        for protocol in protocols:
            self.server.disconnect_client(protocol, ConnectionMessage.DETACH_REQUEST)

    def cleanup_protocol(self, protocol):
        netlog("cleanup_protocol(%s)", protocol)
        # this ensures that from now on we ignore any incoming packets coming
        # from this connection as these could potentially set some keys pressed, etc
        try:
            self._potential_protocols.remove(protocol)
        except ValueError:
            pass
        if source := self._server_sources.pop(protocol, None):
            self.cleanup_source(source)
            if mdns := self.subsystems.get("mdns"):
                add_work_item(mdns.mdns_update)
        self._dispatch_fire("cleanup_protocol", protocol)
        return source

    def cleanup_source(self, source) -> None:
        ptype = "xpra"
        if FULL_INFO > 0:
            ptype = getattr(source, "client_type", "") or "xpra"
        self.server_event("connection-lost", source.uuid)
        self.emit("client-exited", source)

        remaining_sources = tuple(self._server_sources.values())
        if self.ui_driver == source.uuid:
            if len(remaining_sources) == 1:
                self.set_ui_driver(remaining_sources[0])
            else:
                self.set_ui_driver(None)
        source.close()
        netlog("cleanup_source(%s) remaining sources: %s", source, remaining_sources)
        netlog.info("%s client %i disconnected.", ptype, source.counter)
        has_client = len(remaining_sources) > 0
        if not has_client:
            GLib.idle_add(self.last_client_exited)

    def last_client_exited(self) -> None:
        # must run from the UI thread (modifies focus and keys)
        # `exit_with_client` is owned by `SharingServer`:
        sharing = self.subsystems.get("sharing")
        exit_with_client = bool(sharing and sharing.exit_with_client)
        netlog("last_client_exited() exit_with_client=%s", exit_with_client)
        self.emit("last-client-exited")
        if exit_with_client and not self._closing:
            netlog.info("Last client has disconnected, terminating")
            self.clean_quit(False)

    def set_ui_driver(self, source) -> None:
        if source and self.ui_driver == source.uuid:
            return
        log("new ui driver: %s", source)
        if not source:
            self.ui_driver = None
        else:
            self.ui_driver = source.uuid
        self.emit("new-ui-driver", source)

    def get_all_protocols(self) -> list:
        return list(self._potential_protocols) + list(self._server_sources.keys())

    def is_timedout(self, protocol) -> bool:
        v = super().is_timedout(protocol) and protocol not in self._server_sources
        netlog("is_timedout(%s)=%s", protocol, v)
        return v

    def _disconnect_proto_info(self, proto) -> str:
        # only log protocol info if there is more than one client:
        if len(self._server_sources) > 1:
            return " %s" % proto
        return ""

    def init_packet_handlers(self) -> None:
        # ServerCore.init_packet_handlers registers core handlers and dispatches
        # `init_packet_handlers` to all subsystems:
        super().init_packet_handlers()
        if BACKWARDS_COMPATIBLE:
            # no need for main thread:
            self.add_packet_handler("set_deflate", noop)  # removed in v6
            # now moved to XSettingsServer
            self.add_packets("server-settings", main_thread=True)
        self.add_packets("shutdown-server", "exit-server")

    # override so we can set the 'authenticated' flag:
    def process_packet(self, proto, packet: Packet) -> None:
        authenticated = bool(self.get_server_source(proto))
        return super().dispatch_packet(proto, packet, authenticated)

    def handle_invalid_packet(self, proto, packet: Packet) -> None:
        ss = self.get_server_source(proto)
        if not self._closing and not proto.is_closed() and (ss is None or not ss.is_closed()):
            netlog("invalid packet: %s", packet)
            packet_type = packet.get_type()
            netlog.error(f"Error: unknown or invalid packet type {packet_type!r}")
            netlog.error(f" received from {proto}")
        if not ss:
            proto.close()
