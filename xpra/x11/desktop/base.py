# This file is part of Xpra.
# Copyright (C) 2016 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
from typing import Any

from xpra.os_util import gi_import
from xpra.util.screen import log_screen_sizes
from xpra.util.str_fn import csv
from xpra.util.env import envbool
from xpra.net.common import PacketType
from xpra.server import features
from xpra.gtk.util import get_root_size
from xpra.gtk.info import get_screen_sizes
from xpra.gtk.gobject import one_arg_signal
from xpra.x11.gtk.bindings import add_catchall_receiver, remove_catchall_receiver, add_event_receiver
from xpra.x11.xroot_props import XRootPropWatcher
from xpra.x11.bindings.window import X11WindowBindings
from xpra.x11.bindings.keyboard import X11KeyboardBindings
from xpra.x11.server.base import X11ServerBase
from xpra.gtk.error import xsync, xlog
from xpra.log import Logger

GObject = gi_import("GObject")
Gio = gi_import("Gio")

X11Window = X11WindowBindings()
X11Keyboard = X11KeyboardBindings()

log = Logger("server")
windowlog = Logger("server", "window")
mouselog = Logger("server", "mouse")
geomlog = Logger("server", "window", "geometry")
metadatalog = Logger("x11", "metadata")
screenlog = Logger("screen")
iconlog = Logger("icon")

MODIFY_GSETTINGS: bool = envbool("XPRA_MODIFY_GSETTINGS", True)
MULTI_MONITORS: bool = envbool("XPRA_DESKTOP_MULTI_MONITORS", True)


def get_desktop_server_base_classes() -> tuple[type, ...]:
    classes: list[type] = [GObject.GObject]
    if features.rfb:
        from xpra.server.rfb.server import RFBServer
        classes.append(RFBServer)
    classes.append(X11ServerBase)
    return tuple(classes)


DESKTOPSERVER_BASES = get_desktop_server_base_classes()
DesktopServerBaseClass = type('DesktopServerBaseClass', DESKTOPSERVER_BASES, {})
log("DesktopServerBaseClass%s", DESKTOPSERVER_BASES)


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


class DesktopServerBase(DesktopServerBaseClass):
    """
        A server base class for RFB / VNC-like virtual desktop or virtual monitors,
        used with the "start-desktop" subcommand.
    """
    __common_gsignals__: dict[str, tuple] = {
        "x11-xkb-event": one_arg_signal,
        "x11-cursor-event": one_arg_signal,
        "x11-motion-event": one_arg_signal,
        "x11-configure-event": one_arg_signal,
    }

    def __init__(self):
        X11ServerBase.__init__(self)  # pylint: disable=non-parent-init-called
        for c in DESKTOPSERVER_BASES:
            if c != X11ServerBase:
                c.__init__(self)  # pylint: disable=non-parent-init-called
        self.gsettings_modified: dict[str, Any] = {}
        self.root_prop_watcher = None

    def init(self, opts) -> None:
        for c in DESKTOPSERVER_BASES:
            if c != GObject.GObject:
                c.init(self, opts)

    def x11_init(self) -> None:
        X11ServerBase.x11_init(self)
        add_event_receiver(X11Window.get_root_xid(), self)
        add_catchall_receiver("x11-motion-event", self)
        add_catchall_receiver("x11-xkb-event", self)
        with xlog:
            X11Keyboard.selectBellNotification(True)
        if MODIFY_GSETTINGS:
            self.modify_gsettings()
        self.root_prop_watcher = XRootPropWatcher(["WINDOW_MANAGER", "_NET_SUPPORTING_WM_CHECK"])
        self.root_prop_watcher.connect("root-prop-changed", self.root_prop_changed)

    def root_prop_changed(self, watcher, prop: str) -> None:
        iconlog("root_prop_changed(%s, %s)", watcher, prop)
        for window in self._id_to_window.values():
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
        X11ServerBase.do_cleanup(self)
        if MODIFY_GSETTINGS:
            self.restore_gsettings()
        rpw = self.root_prop_watcher
        if rpw:
            self.root_prop_watcher = None
            rpw.cleanup()

    def restore_gsettings(self) -> None:
        do_modify_gsettings(self.gsettings_modified, True)

    def notify_dpi_warning(self, body) -> None:
        """ ignore DPI warnings in desktop mode """

    def print_screen_info(self) -> None:
        super().print_screen_info()
        root_w, root_h = get_root_size()
        log.info(" initial resolution: %ix%i", root_w, root_h)
        sss = get_screen_sizes()
        log_screen_sizes(root_w, root_h, sss)

    def parse_screen_info(self, ss) -> None:
        return self.do_parse_screen_info(ss, ss.desktop_mode_size)

    def notify_screen_changed(self, screen) -> None:
        """
        Screen changes are normally managed by requests or user actions,
        we do not need to send any messages to the client here,
        the monitor window model(s) will take care of it.
        """

    def set_desktop_geometry_attributes(self, w: int, h: int):
        # geometry is not synced with the client's for desktop servers
        pass

    def get_server_mode(self) -> str:
        return "X11 desktop"

    def make_hello(self, source) -> dict[str, Any]:
        capabilities = super().make_hello(source)
        if "features" in source.wants:
            capabilities.setdefault("pointer", {})["grabs"] = True
            capabilities["desktop"] = True
            capabilities.setdefault("window", {}).update({
                "decorations": True,
                "states": ["iconified", "focused"],
            })
            capabilities["screen_sizes"] = get_screen_sizes()
        return capabilities

    def load_existing_windows(self):
        raise NotImplementedError

    def send_initial_windows(self, ss, sharing: bool = False) -> None:
        windowlog("send_initial_windows(%s, %s) will send: %s", ss, sharing, self._id_to_window)
        for model in self._id_to_window.values():
            self.send_new_desktop_model(model, ss, sharing)

    def send_new_desktop_model(self, model, ss, _sharing: bool = False) -> None:
        x, y, w, h = model.get_geometry()
        wid = self._window_to_id[model]
        wprops = self.client_properties.get(wid, {}).get(ss.uuid, {})
        ss.new_window("new-window", wid, model, x, y, w, h, wprops)
        wid = self._window_to_id[model]
        ss.damage(wid, model, 0, 0, w, h)

    def _lost_window(self, window, wm_exiting=False) -> None:
        """ could be used to slow down the refresh rate? """

    def _contents_changed(self, window, event) -> None:
        log("contents changed on %s: %s", window, event)
        self.refresh_window_area(window, event.x, event.y, event.width, event.height)

    def _set_window_state(self, proto, wid: int, window, new_window_state) -> list[str]:
        if not new_window_state:
            return []
        metadatalog("set_window_state%s", (proto, wid, window, new_window_state))
        changes = []
        # boolean: but not a wm_state and renamed in the model... (iconic vs iconified!)
        iconified = new_window_state.get("iconified")
        if iconified is not None and window._updateprop("iconic", iconified):
            changes.append("iconified")
        focused = new_window_state.get("focused")
        if focused is not None and window._updateprop("focused", focused):
            changes.append("focused")
        return changes

    def get_window_position(self, _window) -> tuple[int, int]:
        # we export the whole desktop as a window:
        return 0, 0

    def _process_map_window(self, proto, packet: PacketType) -> None:
        wid, x, y, w, h = (int(x) for x in packet[1:6])
        window = self._id_to_window.get(wid)
        if not window:
            windowlog("cannot map window %s: already removed!", wid)
            return
        geomlog("client mapped window %s - %s, at: %s", wid, window, (x, y, w, h))
        self._window_mapped_at(proto, wid, window, (x, y, w, h))
        if len(packet) >= 8:
            self._set_window_state(proto, wid, window, packet[7])
        if len(packet) >= 7:
            self._set_client_properties(proto, wid, window, packet[6])
        self.refresh_window_area(window, 0, 0, w, h)

    def _process_unmap_window(self, proto, packet: PacketType) -> None:
        wid = int(packet[1])
        window = self._id_to_window.get(wid)
        if not window:
            log("cannot map window %s: already removed!", wid)
            return
        if len(packet) >= 4:
            # optional window_state added in 0.15 to update flags
            # during iconification events:
            self._set_window_state(proto, wid, window, packet[3])
        assert not window.is_OR()
        self._window_mapped_at(proto, wid, window)
        # TODO: handle inconification?
        # iconified = len(packet)>=3 and bool(packet[2])

    def _process_configure_window(self, proto, packet: PacketType) -> None:
        wid, x, y, w, h = (int(x) for x in packet[1:6])
        if len(packet) >= 13 and features.input_devices and not self.readonly:
            pwid = int(packet[10])
            pointer = packet[11]
            modifiers = packet[12]
            device_id = -1
            if self.process_mouse_common(proto, device_id, pwid, pointer):
                self._update_modifiers(proto, wid, modifiers)
        # some "configure-window" packets are only meant for metadata updates:
        skip_geometry = len(packet) >= 10 and packet[9]
        window = self._id_to_window.get(wid)
        if not window:
            geomlog("cannot map window %s: already removed!", wid)
            return
        damage = False
        if len(packet) >= 9:
            damage = bool(self._set_window_state(proto, wid, window, packet[8]))
        if not skip_geometry and not self.readonly:
            owx, owy, oww, owh = window.get_geometry()
            geomlog("_process_configure_window(%s) old window geometry: %s", packet[1:], (owx, owy, oww, owh))
            if oww != w or owh != h:
                window.resize(w, h)
        if len(packet) >= 7:
            cprops = packet[6]
            if cprops:
                metadatalog("window client properties updates: %s", cprops)
                self._set_client_properties(proto, wid, window, cprops)
        self._window_mapped_at(proto, wid, window, (x, y, w, h))
        if damage:
            self.refresh_window_area(window, 0, 0, w, h)

    def _adjust_pointer(self, proto, device_id: int, wid: int, pointer):
        mouselog("_adjust_pointer%s", (proto, device_id, wid, pointer))
        window = self._id_to_window.get(wid)
        if not window:
            mouselog("adjust pointer: no window, suspending cursor")
            self.suspend_cursor(proto)
            return None
        pointer = super()._adjust_pointer(proto, device_id, wid, pointer)
        # maybe the pointer is off-screen:
        ww, wh = window.get_dimensions()
        x, y = pointer[:2]
        if x < 0 or x >= ww or y < 0 or y >= wh:
            mouselog("adjust pointer: pointer outside desktop, suspending cursor")
            self.suspend_cursor(proto)
            return None
        self.restore_cursor(proto)
        return pointer

    def _move_pointer(self, device_id: int, wid: int, pos, props=None):
        if wid >= 0:
            window = self._id_to_window.get(wid)
            if not window:
                mouselog("_move_pointer(%s, %s) invalid window id", wid, pos)
                return
        with xsync:
            X11ServerBase._move_pointer(self, device_id, wid, pos, props)

    def _process_close_window(self, proto, packet: PacketType) -> None:
        # disconnect?
        pass

    def _process_desktop_size(self, proto, packet: PacketType) -> None:
        """
        Usually, desktop servers don't need to do anything when the client's geometry changes.
        """

    def calculate_workarea(self, w: int, h: int):
        """
        The workarea is managed server side by the window manager,
        so we don't need to apply any changes here
        """

    def make_dbus_server(self) -> None:
        from xpra.x11.dbus.x11_dbus_server import X11_DBUS_Server
        self.dbus_server = X11_DBUS_Server(self, os.environ.get("DISPLAY", "").lstrip(":"))

    def show_all_windows(self) -> None:
        log.warn("Warning: show_all_windows not implemented for desktop server")

    def do_make_screenshot_packet(self) -> tuple:
        log("grabbing screenshot")
        regions = []
        offset_x, offset_y = 0, 0
        for wid in reversed(sorted(self._id_to_window.keys())):
            window = self._id_to_window.get(wid)
            log("screenshot: window(%s)=%s", wid, window)
            if window is None:
                continue
            if not window.is_managed():
                log("screenshot: window %s is not/no longer managed", wid)
                continue
            x, y, w, h = window.get_geometry()
            log("screenshot: geometry(%s)=%s", window, (x, y, w, h))
            try:
                with xsync:
                    img = window.get_image(0, 0, w, h)
            except Exception:
                log.warn("screenshot: window %s could not be captured", wid)
                continue
            if img is None:
                log.warn("screenshot: no pixels for window %s", wid)
                continue
            log("screenshot: image=%s, size=%s", img, img.get_size())
            if img.get_pixel_format() not in ("RGB", "RGBA", "XRGB", "BGRX", "ARGB", "BGRA"):
                log.warn("window pixels for window %s using an unexpected rgb format: %s", wid, img.get_pixel_format())
                continue
            regions.append((wid, offset_x + x, offset_y + y, img))
            # tile them horizontally:
            offset_x += w
            offset_y += 0
        return self.make_screenshot_packet_from_regions(regions)
