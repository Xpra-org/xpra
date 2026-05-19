# This file is part of Xpra.
# Copyright (C) 2016 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
from typing import Any

from xpra.os_util import gi_import
from xpra.util.str_fn import csv
from xpra.util.env import envbool
from xpra.net.common import Packet
from xpra.util.gobject import one_arg_signal, to_gsignals
from xpra.server.base import ServerBase
from xpra.x11.dispatch import add_catchall_receiver, remove_catchall_receiver, add_event_receiver
from xpra.x11.bindings.core import get_root_xid
from xpra.x11.error import xlog
from xpra.log import Logger

GObject = gi_import("GObject")
Gio = gi_import("Gio")

log = Logger("server")
windowlog = Logger("server", "window")
geomlog = Logger("server", "window", "geometry")
metadatalog = Logger("x11", "metadata")
screenlog = Logger("screen")
iconlog = Logger("icon")

MODIFY_GSETTINGS: bool = envbool("XPRA_MODIFY_GSETTINGS", True)
MULTI_MONITORS: bool = envbool("XPRA_DESKTOP_MULTI_MONITORS", True)


def do_modify_gsettings(defs: dict[str, Any], value=False) -> dict[str, Any]:
    modified = {}
    try:
        schemas = Gio.SettingsSchemaSource.get_default().list_schemas(True)
    except AttributeError:
        schemas = Gio.Settings.list_schemas()
    for schema, attributes in defs.items():
        if schema not in schemas:
            continue
        try:
            s = Gio.Settings.new(schema_id=schema)
            restore = []
            for attribute in attributes:
                v = s.get_boolean(attribute)
                if v:
                    s.set_boolean(attribute, value)
                    restore.append(attribute)
            if restore:
                modified[schema] = restore
        except Exception as e:
            log("error accessing schema '%s' and attributes %s", schema, attributes, exc_info=True)
            log.error("Error accessing schema '%s' and attributes %s:", schema, csv(attributes))
            log.estr(e)
    return modified


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
        self.gsettings_modified: dict[str, Any] = {}
        self.root_prop_watcher = None
        self.session_type = "X11 desktop"
        # Desktop servers expose a fixed virtual monitor meant to match a
        # real display, so a single sensible default beats the 8K seamless
        # default. The display subsystem reads this in `get_default_initial_res`.
        display = self.subsystems["display"]
        display.default_resolution = "1920x1080"
        # Desktop variants present a fixed virtual monitor; never reshape
        # the screen layout to match the client's monitors.
        display.mirror_client_layout = False

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
        # try to suspend animations:
        self.gsettings_modified = do_modify_gsettings({
            "org.mate.interface": ("gtk-enable-animations", "enable-animations"),
            "org.gnome.desktop.interface": ("enable-animations",),
            "com.deepin.wrap.gnome.desktop.interface": ("enable-animations",),
        })

    def do_cleanup(self) -> None:
        remove_catchall_receiver("x11-motion-event", self)
        super().do_cleanup()
        if MODIFY_GSETTINGS:
            self.restore_gsettings()
        if rpw := self.root_prop_watcher:
            self.root_prop_watcher = None
            rpw.cleanup()

    def restore_gsettings(self) -> None:
        do_modify_gsettings(self.gsettings_modified, True)

    def notify_screen_changed(self, screen) -> None:
        """
        Screen changes are normally managed by requests or user actions,
        we do not need to send any messages to the client here,
        the monitor window model(s) will take care of it.
        """

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
