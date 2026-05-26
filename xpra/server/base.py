# This file is part of Xpra.
# Copyright (C) 2011 Serviware (Arthur Huillet, <ahuillet@serviware.com>)
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
from time import monotonic
from typing import Any

from xpra.server.common import get_sources_by_type
from xpra.server.core import ServerCore, SIGNALS as CORE_SIGNALS
from xpra.server.source.events import EventConnection
from xpra.common import noop
from xpra.net.common import Packet, PacketElement, FULL_INFO, BACKWARDS_COMPATIBLE
from xpra.util.objects import merge_dicts
from xpra.util.str_fn import Ellipsizer
from xpra.os_util import POSIX
from xpra.log import Logger

log = Logger("server")
eventslog = Logger("events")

SIGNALS: dict[str, int] = {
    **CORE_SIGNALS,
    "last-client-exited": 0,
    "client-exited": 1,
    "new-ui-driver": 1,
}
log("signals: %s", SIGNALS)


class ServerBase(ServerCore):
    """
    This is the base class for seamless and desktop servers. (not proxy servers)
    It provides all the generic functions but is not tied
    to a specific backend (X11 or otherwise).
    See X11ServerBase and other platform specific subclasses.
    """
    __signals__ = SIGNALS

    def init_subsystems(self) -> None:
        # Variant servers (seamless, desktop, monitor, shadow, ...) override the
        # `get_*_subsystem_class()` hooks to swap in their own subclasses.
        for cls in self.get_subsystem_classes():
            self.add_subsystem(cls)

    def get_subsystem_classes(self) -> tuple[type, ...]:
        """
        Return the ordered tuple of instance-based subsystem classes to
        construct for this server. Variants (seamless, desktop, monitor,
        shadow, ...) override the per-subsystem hooks below to swap in their
        own subclasses.
        """
        from xpra.server import features
        classes: list[type] = []
        if features.gtk:
            if gtk_class := self.get_gtk_subsystem_class():
                classes.append(gtk_class)
        elif features.x11:
            from xpra.x11.subsystem.x11init import X11Init
            classes.append(X11Init)
        if features.ping:
            from xpra.server.subsystem.ping import PingServer
            classes.append(PingServer)
        if features.bandwidth:
            from xpra.server.subsystem.bandwidth import BandwidthManager
            classes.append(BandwidthManager)
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
            from xpra.server.subsystem.idle import IdleTimeoutManager
            classes.append(IdleTimeoutManager)
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
            from xpra.server.subsystem.dbus import DbusManager
            classes.append(DbusManager)
        # EncryptionServer is unconditional - it gracefully no-ops when no
        # encryption is configured on a given socket.
        from xpra.server.subsystem.encryption import EncryptionServer
        classes.append(EncryptionServer)
        if features.command:
            from xpra.server.subsystem.menu import MenuServer
            classes.append(MenuServer)
        if features.logging:
            from xpra.server.subsystem.logging import LoggingManager
            classes.append(LoggingManager)
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
            classes.append(self.get_clipboard_subsystem_class())
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
        if features.rfb:
            from xpra.server.rfb.server import RFBServer
            classes.append(RFBServer)
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
        from xpra.server.subsystem.client_session import ClientSessionServer
        classes.append(ClientSessionServer)
        from xpra.server.subsystem.shutdown import ShutdownServer
        classes.append(ShutdownServer)
        if features.cursor:
            classes.append(self.get_cursor_subsystem_class())
        if features.x11 and features.display:
            from xpra.x11.subsystem.xsettings import XSettingsServer
            classes.append(XSettingsServer)
        return tuple(classes)

    @staticmethod
    def get_gtk_subsystem_class() -> type | None:
        from xpra.server import features
        if features.x11:
            from xpra.x11.subsystem.gtk import GtkX11Server
            return GtkX11Server
        from xpra.server.subsystem.gtk import GTKServer
        return GTKServer

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

    def get_cursor_subsystem_class(self) -> type:
        from xpra.server import features
        if features.x11:
            from xpra.x11.subsystem.cursor import XCursorServer
            return XCursorServer
        from xpra.server.subsystem.cursor import CursorManager
        return CursorManager

    def get_clipboard_subsystem_class(self) -> type:
        from xpra.server.subsystem.clipboard import ClipboardManager
        return ClipboardManager

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

    def init(self, opts) -> None:
        # from now on, use the logger for parsing errors:
        from xpra.scripts import config  # pylint: disable=import-outside-toplevel
        config.warn = log.warn
        # ServerCore.init handles connection-layer setup and dispatches `init`
        # to every entry in self.subsystems
        super().init(opts)

    def setup(self) -> None:
        log("starting component init")
        # ServerCore.setup dispatches `setup` to all subsystems:
        super().setup()

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

    def get_display_name(self) -> str:
        display = self.subsystems.get("display")
        return display.get_display_name() if display else os.environ.get("DISPLAY", "")

    def get_xpra_sessions(self) -> dict[str, Any]:
        from xpra.scripts.sessions import get_xpra_sessions  # pylint: disable=import-outside-toplevel
        return get_xpra_sessions(self.dotxpra, matching_display=self.get_display_name())

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

    def update_all_server_settings(self, reset: bool = False) -> None:
        pass  # may be overridden in subclasses (ie: x11 server)

    ######################################################################
    # hello:
    def get_server_features(self, server_source=None) -> dict[str, Any]:
        # these are flags that have been added over time with new versions
        # to expose new server features:
        return self._dispatch_merge("get_server_features", server_source)

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
                mixin_info = sub.get_ui_info(proto, **kwargs)
                log("%s.get_ui_info(%s, ..)=%r", prefix, proto, Ellipsizer(mixin_info))
                merge_dicts(info, mixin_info)
        return info

    def get_threaded_info(self, proto, **kwargs) -> dict[str, Any]:
        log("ServerBase.get_threaded_info%s", (proto, kwargs))
        start = monotonic()
        info: dict[str, Any] = ServerCore.get_threaded_info(self, proto, **kwargs)
        sources = tuple(self._server_sources.values())
        client_uuids = kwargs.get("client_uuids", ())
        if client_uuids:
            sources = tuple(ss for ss in sources if ss.uuid in client_uuids)
        log("threaded info sources(%i)=%s", client_uuids, sources)
        info.update(self.get_sources_info(proto, sources))
        log("ServerBase.get_info took %.1fms", 1000.0 * (monotonic() - start))
        return info

    def _process_server_settings(self, proto, packet: Packet) -> None:
        # only used by x11 servers
        pass

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
