# This file is part of Xpra.
# Copyright (C) 2011 Serviware (Arthur Huillet, <ahuillet@serviware.com>)
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
from typing import Any

from xpra.server.common import get_sources_by_type
from xpra.server.core import ServerCore, SIGNALS as CORE_SIGNALS
from xpra.server.source.events import EventConnection
from xpra.net.common import PacketElement
from xpra.util import subsystem as dispatch
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
        """Return the ordered subsystem classes, using this server's backend selectors."""
        from xpra.server.factory import get_server_subsystems
        return get_server_subsystems(self)

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

    def get_bell_subsystem_class(self) -> type | None:
        # only the backends that have a bell event source to hook into
        # provide a subsystem - there is nothing generic to fall back on:
        from xpra.server import features
        if features.x11:
            from xpra.x11.subsystem.bell import X11BellServer
            return X11BellServer
        return None

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
        from xpra import config  # pylint: disable=import-outside-toplevel
        config.warn = log.warn
        # ServerCore.init dispatches `init` to every entry in self.subsystems,
        # including the `network` subsystem which handles the connection layer
        super().init(opts)

    def server_is_ready(self) -> None:
        super().server_is_ready()
        self.server_event("ready")

    def do_cleanup(self) -> None:
        # ServerCore.cleanup has already dispatched `cleanup` to all subsystems
        # before invoking do_cleanup; we just emit the server event here.
        self.server_event("exit")
        log("do_cleanup()")

    # Display-subsystem hooks that variant servers may override. The
    # DisplayManager subsystem calls these via `self.server.X(...)` so
    # that the variant override fires; the defaults here delegate back
    # to the subsystem (where applicable) or no-op.
    def set_desktop_geometry(self, width: int, height: int) -> None:
        """ optionally overridden by server variants """

    def set_workarea(self, workarea) -> None:
        """ optionally overridden by server variants """

    def set_workareas(self, workareas) -> None:
        """ optionally overridden by server variants """

    def calculate_desktops(self) -> None:
        """ optionally overridden by server variants """

    def set_dpi(self, xdpi: int, ydpi: int) -> None:
        """ optionally overridden by server variants """

    def get_capture_adapter_luid(self) -> bytes:
        """ Optionally identify the capture adapter for GPU encoder device selection. """
        return b""

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
        return get_displays(self.network.dotxpra, display_names=(self.get_display_name(), ))

    def get_display_name(self) -> str:
        display = self.subsystems.get("display")
        return display.get_display_name() if display else os.environ.get("DISPLAY", "")

    def get_xpra_sessions(self) -> dict[str, Any]:
        from xpra.scripts.sessions import get_xpra_sessions  # pylint: disable=import-outside-toplevel
        return get_xpra_sessions(self.network.dotxpra, matching_display=self.get_display_name())

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

    ######################################################################
    # hello:
    def get_server_features(self, server_source=None) -> dict[str, Any]:
        # these are flags that have been added over time with new versions
        # to expose new server features:
        return dispatch.merge(self.subsystems, "get_server_features", server_source)

    def send_hello(self, server_source, server_cipher: dict) -> None:
        capabilities = self.make_hello(server_source)
        if server_cipher:
            capabilities.update(server_cipher)
        server_source.send_hello(capabilities)

    ######################################################################
    # info:
    def get_threaded_info(self, proto, **kwargs) -> dict[str, Any]:
        info = super().get_threaded_info(proto, **kwargs)
        if client_session := self.get_subsystem("client-session"):
            info.update(client_session.get_sources_info(proto, client_uuids=kwargs.get("client_uuids", ())))
        return info
