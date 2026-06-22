# This file is part of Xpra.
# Copyright (C) 2016 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
from typing import Any

from xpra.os_util import gi_import
from xpra.util.env import envbool
from xpra.net.common import Packet
from xpra.util.gobject import one_arg_signal, to_gsignals
from xpra.server.base import ServerBase
from xpra.x11.dispatch import add_catchall_receiver, remove_catchall_receiver, add_event_receiver
from xpra.x11.bindings.core import get_root_xid
from xpra.x11.error import xlog
from xpra.log import Logger

GObject = gi_import("GObject")

log = Logger("server")
windowlog = Logger("server", "window")
geomlog = Logger("server", "window", "geometry")
metadatalog = Logger("x11", "metadata")
screenlog = Logger("screen")
iconlog = Logger("icon")

MODIFY_GSETTINGS: bool = envbool("XPRA_MODIFY_GSETTINGS", True)
MULTI_MONITORS: bool = envbool("XPRA_DESKTOP_MULTI_MONITORS", True)

# GSettings that the desktop server applies as a baseline (via the `gsettings` subsystem)
# to suspend compositor animations for the duration of the session - {(schema, key): gvariant_text}:
ANIMATION_GSETTINGS: dict[tuple[str, str], str] = {
    ("org.mate.interface", "gtk-enable-animations"): "false",
    ("org.mate.interface", "enable-animations"): "false",
    ("org.gnome.desktop.interface", "enable-animations"): "false",
    ("com.deepin.wrap.gnome.desktop.interface", "enable-animations"): "false",
}


SIGNALS = to_gsignals(ServerBase.__signals__)
SIGNALS.update({
    "x11-xkb-event": one_arg_signal,
    "x11-cursor-event": one_arg_signal,
    "x11-motion-event": one_arg_signal,
    "x11-configure-event": one_arg_signal,
})


class DesktopServerBase(GObject.GObject, ServerBase):
    """
        A server base class for RFB / VNC-like virtual desktop or virtual monitors,
        used with the `desktop` subcommand.
    """
    __common_gsignals__ = SIGNALS

    def __init__(self):
        GObject.GObject.__init__(self)
        ServerBase.__init__(self)
        self.root_prop_watcher = None
        self.session_type = "X11 desktop"

    def get_display_subsystem_class(self) -> type:
        from xpra.x11.desktop.display import XpraDesktopDisplayManager
        return XpraDesktopDisplayManager

    def get_pointer_subsystem_class(self) -> type:
        from xpra.x11.desktop.pointer import XpraDesktopPointerManager
        return XpraDesktopPointerManager

    def setup(self) -> None:
        super().setup()
        add_event_receiver(get_root_xid(), self)
        add_catchall_receiver("x11-motion-event", self)
        add_catchall_receiver("x11-xkb-event", self)
        with xlog:
            from xpra.x11.bindings.keyboard import X11KeyboardBindings
            X11KeyboardBindings().selectBellNotification(True)
        if MODIFY_GSETTINGS:
            self.modify_gsettings()
        from xpra.x11.xroot_props import XRootPropWatcher
        self.root_prop_watcher = XRootPropWatcher(["WINDOW_MANAGER", "_NET_SUPPORTING_WM_CHECK"])
        self.root_prop_watcher.connect("root-prop-changed", self.root_prop_changed)

    def root_prop_changed(self, watcher, prop: str) -> None:
        iconlog("root_prop_changed(%s, %s)", watcher, prop)
        for window in self.subsystems["window"].models():
            window.update_wm_name()
            window.update_icon()

    def modify_gsettings(self) -> None:
        # suspend animations for the duration of the session by feeding the
        # `gsettings` subsystem a baseline it applies (and restores on shutdown):
        gsettings = self.get_subsystem("gsettings")
        if not gsettings:
            log("modify_gsettings() the gsettings subsystem is not available")
            return
        gsettings.defaults.update(ANIMATION_GSETTINGS)
        gsettings.update_gsettings()

    def do_cleanup(self) -> None:
        remove_catchall_receiver("x11-motion-event", self)
        super().do_cleanup()
        if rpw := self.root_prop_watcher:
            self.root_prop_watcher = None
            rpw.cleanup()

    def set_desktop_geometry_attributes(self, w: int, h: int):
        # geometry is not synced with the client's for desktop servers
        pass

    def get_server_features(self, source=None) -> dict[str, Any]:
        capabilities = super().get_server_features(source)
        capabilities.setdefault("pointer", {})["grabs"] = True
        capabilities["desktop"] = True
        capabilities.setdefault("window", {}).update({
            "decorations": True,
            "states": ["iconified", "focused"],
        })
        return capabilities

    def _process_desktop_size(self, proto, packet: Packet) -> None:
        """
        Usually, desktop servers don't need to do anything when the client's geometry changes.
        """

    def make_dbus_server(self):
        from xpra.x11.dbus.x11_dbus_server import X11_DBUS_Server
        return X11_DBUS_Server(self, os.environ.get("DISPLAY", "").lstrip(":"))
