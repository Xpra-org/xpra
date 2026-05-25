# This file is part of Xpra.
# Copyright (C) 2011 Serviware (Arthur Huillet, <ahuillet@serviware.com>)
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
from time import sleep
from typing import Any, NoReturn

from xpra.os_util import gi_import
from xpra.scripts.config import InitExit
from xpra.server.common import get_sources_by_type
from xpra.server.source.display import DisplayConnection
from xpra.util.env import envbool
from xpra.exit_codes import ExitCode
from xpra.net.common import PacketElement
from xpra.server import ServerExitMode, CLOBBER_UPGRADE
from xpra.util.gobject import one_arg_signal, n_arg_signal, to_gsignals
from xpra.x11.common import get_wm_name
from xpra.x11.bindings.core import constants, get_root_xid
from xpra.x11.bindings.window import X11WindowBindings
from xpra.server.base import ServerBase
from xpra.x11.error import xsync, XError
from xpra.log import Logger

GObject = gi_import("GObject")

log = Logger("server")
focuslog = Logger("server", "focus")
grablog = Logger("server", "grab")
windowlog = Logger("server", "window")
geomlog = Logger("server", "window", "geometry")
traylog = Logger("server", "tray")
workspacelog = Logger("x11", "workspace")
metadatalog = Logger("x11", "metadata")
framelog = Logger("x11", "frame")
eventlog = Logger("x11", "events")
pointerlog = Logger("x11", "pointer")
screenlog = Logger("x11", "screen")

SubstructureNotifyMask = constants["SubstructureNotifyMask"]

DUMMY_DPI = envbool("XPRA_DUMMY_DPI", True)


GSIGNALS = to_gsignals(ServerBase.__signals__)
GSIGNALS.update({
    "x11-child-map-event": one_arg_signal,
    "server-event": n_arg_signal(2),
    # X11 dispatch signals consumed by the bell / cursor subsystems.
    # Declared here (not on the subsystems) because X11 dispatch requires
    # a GObject receiver - see `BellServer` / `XCursorServer` docstrings.
    "x11-xkb-event": one_arg_signal,
    "x11-cursor-event": one_arg_signal,
})


def log_composite_error(msg: str) -> NoReturn:
    log.error("Xpra 'seamless' server runs as a compositing manager")
    log.error(" and the XComposite extension is required,")
    log.error(" the server cannot be started")
    raise InitExit(ExitCode.COMPONENT_MISSING, "the composite extension is not available: %s" % msg)


class SeamlessServer(GObject.GObject, ServerBase):
    __gsignals__ = GSIGNALS

    def __init__(self, clobber):
        self.clobber = clobber
        GObject.GObject.__init__(self)
        ServerBase.__init__(self)
        self.session_type = "seamless"
        self._xsettings_enabled = True

    def get_display_subsystem_class(self) -> type:
        from xpra.x11.server.display import X11SeamlessDisplayManager
        return X11SeamlessDisplayManager

    def get_window_subsystem_class(self) -> type:
        from xpra.x11.subsystem.window import SeamlessWindowServer
        return SeamlessWindowServer

    def init(self, opts) -> None:
        if int(opts.sync_xvfb or 0) > 0:
            from xpra.x11.subsystem.root_overlay import RootOverlay
            self.subsystems[RootOverlay.PREFIX] = RootOverlay(self)
        super().init(opts)

        def log_server_event(_, event, *_args):
            eventlog("server-event: %s", event)

        self.connect("server-event", log_server_event)

    def setup(self) -> None:
        super().setup()
        self.validate_display()
        # the window subsystem owns the `Wm` instance. Create it here
        # because we need it ready before the main loop starts (which
        # drives load_existing_windows etc.), but after super().setup()
        # has constructed the subsystem instance.
        window_sub = self.subsystems["window"]
        from xpra.x11.wm import Wm
        window_sub._wm = Wm(window_sub.wm_name)
        window_sub._wm.init_atoms()
        self.receive_root_events()
        self.init_wm()

    def get_child_env(self) -> dict[str, str]:
        env: dict[str, str] = super().get_child_env()
        if "GDK_BACKEND" not in env:
            env["GDK_BACKEND"] = "x11"
        if os.environ.get("NO_AT_BRIDGE") is None:
            env["NO_AT_BRIDGE"] = "1"
        return env

    def validate_display(self) -> None:
        try:
            from xpra.x11.bindings.composite import XCompositeBindings
        except ImportError as e:
            log("validate_display()", exc_info=True)
            log_composite_error("the XCompositeBindings bindings cannot be loaded: %s" % e)
        if not XCompositeBindings().hasXComposite():
            log_composite_error("the composite extension is not available on this display")
        # check for an existing window manager:
        from xpra.x11.wm_check import wm_check
        if not wm_check(self.clobber & CLOBBER_UPGRADE):
            raise InitExit(ExitCode.WM_ERROR, "another window manager seems to be running on this display")

    def receive_root_events(self):
        # Do this before creating the Wm object, to avoid clobbering its
        # selecting SubstructureRedirect.
        with xsync:
            xid = get_root_xid()
            X11Window = X11WindowBindings()
            event_mask = X11Window.getEventMask(xid) | SubstructureNotifyMask
            X11Window.setEventMask(xid, event_mask)
        from xpra.x11.dispatch import add_event_receiver
        add_event_receiver(xid, self)

    def init_wm(self) -> None:
        from xpra.x11.selection.common import AlreadyOwned
        window_sub = self.subsystems["window"]
        # Create the WM object
        x11_errors = []
        while True:
            try:
                with xsync:
                    window_sub._wm.setup(self.clobber)
                    break
            except AlreadyOwned:
                log("Error: cannot create our window manager", exc_info=True)
                display = os.environ.get("DISPLAY", "")
                # make sure we don't kill the vfb since we don't own it:
                self._exit_mode = ServerExitMode.EXIT
                wm_name = "another window manager"
                with xsync:
                    wm_name = f"{get_wm_name()!r}"
                err = f"{wm_name} is already active on display {display}"
                from xpra.scripts.config import InitException  # pylint: disable=import-outside-toplevel
                raise InitException(err) from None
            except XError as e:
                x11_errors.append(e)
                count = len(x11_errors)
                if count > 5:
                    log.error("Error: failed to initialize the window manager")
                    for x in list(set(str(x) for x in x11_errors)):
                        log.error(" %s", x)
                    raise
                # retry:
                sleep(0.010 * count)
        window_sub._wm.connect("quit", lambda _: self.clean_quit(True))
        window_sub._wm.connect("show-desktop", window_sub._show_desktop)

    def do_cleanup(self) -> None:
        window_sub = self.subsystems.get("window")
        if window_sub:
            window_sub.cancel_all_configure_damage()
            if window_sub._wm:
                window_sub._wm.cleanup()
                window_sub._wm = None
            if window_sub._has_grab:
                # normally we set this value when we receive the NotifyUngrab
                # but at this point in the cleanup, we probably won't, so force set it:
                window_sub._has_grab = 0
                self.x11_ungrab()
        super().do_cleanup()

    def last_client_exited(self) -> None:
        # last client is gone:
        super().last_client_exited()
        window_sub = self.subsystems.get("window")
        if window_sub and window_sub._has_grab:
            window_sub._has_grab = 0
            self.x11_ungrab()

    def __repr__(self):
        return "X11-Seamless-Server"

    # GObject signal handler - delegates to the window subsystem.
    # GObject looks up default handlers as `do_<signal-name>` on the
    # emitter instance, which is this variant class. The subsystem owns
    # the actual logic, so just forward.
    def do_x11_child_map_event(self, event) -> None:
        window_sub = self.subsystems.get("window")
        if window_sub:
            window_sub.do_x11_child_map_event(event)

    def server_event(self, event_type: str, *args: PacketElement) -> None:
        super().server_event(event_type, *args)
        self.emit("server-event", event_type, args)

    def get_server_features(self, server_source=None) -> dict[str, Any]:
        from xpra.x11.subsystem.window import WINDOW_SIGNALS
        capabilities = super().get_server_features(server_source)
        capabilities.setdefault("pointer", {})["grabs"] = True
        capabilities.setdefault("window", {}).update({
            "frame-extents": True,
            "configure.delta": True,
            "signals": WINDOW_SIGNALS,
            "dragndrop": True,
            "states": [
                "iconified", "focused", "fullscreen",
                "above", "below",
                "sticky", "iconified", "maximized",
            ],
        })
        return capabilities

    ##########################################################################
    # info:
    #
    def get_ui_info(self, proto, **kwargs) -> dict[str, Any]:
        info = super().get_ui_info(proto, **kwargs)
        # _NET_WM_NAME:
        window_sub = self.subsystems.get("window")
        if window_sub and (wm := window_sub._wm):
            info.setdefault("state", {})["window-manager-name"] = wm.get_net_wm_name()
        return info

    ##########################################################################
    # Manage the virtual screen:
    #

    def set_screen_geometry_attributes(self, w: int, h: int) -> None:
        # only run the default code if there are no clients,
        # when we have clients, this should have been done already
        # in the code that synchronizes the screen resolution
        if not self._server_sources:
            self.subsystems["display"].set_screen_geometry_attributes(w, h)

    def calculate_desktops(self) -> None:
        window_sub = self.subsystems.get("window")
        wm = window_sub._wm if window_sub else None
        if not wm:
            return
        count = 1
        sources = get_sources_by_type(self, DisplayConnection)
        for ss in sources:
            if ss.desktops:
                count = max(count, ss.desktops)
        count = max(1, min(20, count))
        names: list[str] = []
        for i in range(count):
            name = "Main" if i == 0 else f"Desktop {i + 1}"
            for ss in sources:
                if ss.desktops and i < len(ss.desktop_names) and ss.desktop_names[i]:
                    v = ss.desktop_names[i]
                    if v != "0" or i != 0:
                        name = v
            names.append(name)
        from xpra.x11.xroot_props import set_desktop_list
        set_desktop_list(names)

    def set_workarea(self, workarea) -> None:
        from xpra.x11.xroot_props import set_workarea
        set_workarea(workarea.x, workarea.y, workarea.width, workarea.height)

    def set_desktop_geometry(self, width: int, height: int) -> None:
        window_sub = self.subsystems.get("window")
        if window_sub and (wm := window_sub._wm):
            wm.update_desktop_geometry(width, height)

    def set_dpi(self, xdpi: int, ydpi: int) -> None:
        # this is used by some newer versions of the dummy driver (xf86-driver-dummy)
        # (and will not be honoured by anything else..)
        if DUMMY_DPI:
            from xpra.x11.xroot_props import root_set
            root_set("dummy-constant-xdpi", "u32", xdpi)
            root_set("dummy-constant-ydpi", "u32", ydpi)
            screenlog("set_dpi(%i, %i)", xdpi, ydpi)

    def make_dbus_server(self):
        from xpra.x11.dbus.x11_dbus_server import X11_DBUS_Server
        return X11_DBUS_Server(self, os.environ.get("DISPLAY", "").lstrip(":"))


GObject.type_register(SeamlessServer)
