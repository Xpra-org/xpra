# This file is part of Xpra.
# Copyright (C) 2025 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.platform.posix.gui import x11_bindings
from xpra.common import noop
from xpra.log import Logger

log = Logger("posix")


def get_resource_manager() -> bytes | None:
    try:
        from xpra.gtk.util import get_default_root_window
        from xpra.x11.prop import prop_get
        root = get_default_root_window()
        xid = root.get_xid()
        value = prop_get(xid, "RESOURCE_MANAGER", "latin1", ignore_errors=True)
        if value is not None:
            return value.encode("utf-8")
    except (ImportError, UnicodeEncodeError):
        log.error("failed to get RESOURCE_MANAGER", exc_info=True)
    return None


class X11DisplayPropsWatcher:
    """
    XSettings + root-window property watching (DPI, workarea, desktop names,
    window stacking), feeding the `display` and `window` subsystems. This is
    an X11-binding based, OS/display-server concern, not a toolkit one.
    """

    def __init__(self, display_client, xsettings_enabled: bool = True):
        self.display = display_client
        self.xsettings_enabled = xsettings_enabled
        self._xsettings_watcher = None
        self._root_props_watcher = None
        self._x11_filter = None

    def setup(self) -> None:
        # wait for handshake to complete:
        if x11_bindings():
            self.display.client.after_handshake(self.do_setup_xprops)

    def init_x11_filter(self) -> None:
        if self._x11_filter:
            return
        try:
            from xpra.x11.gtk.bindings import init_x11_filter  # @UnresolvedImport, @UnusedImport
            self._x11_filter = init_x11_filter()
            log("x11_filter=%s", self._x11_filter)
        except Exception as e:
            log("init_x11_filter()", exc_info=True)
            log.error("Error: failed to initialize X11 GDK filter:")
            log.estr(e)
            self._x11_filter = None

    def cleanup(self) -> None:
        log("cleanup() xsettings_watcher=%s, root_props_watcher=%s", self._xsettings_watcher, self._root_props_watcher)
        if self._x11_filter:
            self._x11_filter = None
            from xpra.x11.gtk.bindings import cleanup_x11_filter  # @UnresolvedImport, @UnusedImport
            cleanup_x11_filter()
        if xw := self._xsettings_watcher:
            self._xsettings_watcher = None
            xw.cleanup()
        if rw := self._root_props_watcher:
            self._root_props_watcher = None
            rw.cleanup()

    def do_setup_xprops(self, *args) -> None:
        log("do_setup_xprops(%s)", args)
        root_props = []
        if self.xsettings_enabled:
            root_props += ["RESOURCE_MANAGER", "_NET_WORKAREA", "_NET_CURRENT_DESKTOP"]
        window = self.display.get_subsystem("window")
        if window and window.server_window_stacking:
            root_props.append("_NET_CLIENT_LIST_STACKING")
        if not root_props:
            return
        try:
            self.init_x11_filter()
            # pylint: disable=import-outside-toplevel
            from xpra.x11.xroot_props import XRootPropWatcher, GTK_WORKAREAS_PREFIX
            if self.xsettings_enabled and self._xsettings_watcher is None:
                from xpra.x11.subsystem.xsettings_manager import XSettingsWatcher
                self._xsettings_watcher = XSettingsWatcher()
                self._xsettings_watcher.connect("xsettings-changed", self._handle_xsettings_changed)
                self._handle_xsettings_changed()
            if self._root_props_watcher is None:
                # the workarea property name varies with the current desktop, so match on its prefix:
                prefixes = (GTK_WORKAREAS_PREFIX, ) if self.xsettings_enabled else ()
                self._root_props_watcher = XRootPropWatcher(root_props, prefixes)
                self._root_props_watcher.connect("root-prop-changed", self._handle_root_prop_changed)
                if self.xsettings_enabled:
                    self._root_props_watcher.do_notify("RESOURCE_MANAGER")
                if "_NET_CLIENT_LIST_STACKING" in root_props:
                    self._root_props_watcher.do_notify("_NET_CLIENT_LIST_STACKING")
        except ImportError as e:
            log("do_setup_xprops%s", args, exc_info=True)
            log.error("Error: failed to load X11 properties/settings bindings:")
            log.estr(e)
            log.error(" root window properties will not be propagated")

    def _get_xsettings(self):
        if xw := self._xsettings_watcher:
            with log.trap_error("Error retrieving XSETTINGS"):
                return xw.get_settings()
        return None

    def send_xsettings(self, settings: dict) -> None:
        # sent as the `xsettings` setting of a `setting-change` packet,
        # older servers get a legacy `server-settings` packet instead
        # (see `LEGACY_SETTING_PACKETS`)
        self.display.client.send_setting_change("xsettings", settings)

    def _handle_xsettings_changed(self, *_args) -> None:
        settings = self._get_xsettings()
        log("xsettings_changed new value=%s", settings)
        if settings is not None:
            self.send_xsettings({"xsettings-blob": settings})

    def _handle_root_prop_changed(self, obj, prop) -> None:
        log("root_prop_changed(%s, %s)", obj, prop)
        if prop == "_NET_CLIENT_LIST_STACKING":
            window = self.display.get_subsystem("window")
            if window:
                window.send_window_stacking(self.get_window_stacking(window))
            return
        if prop == "RESOURCE_MANAGER":
            rm = get_resource_manager()
            if rm is not None:
                self.send_xsettings({"resource-manager": rm})
            return
        from xpra.x11.xroot_props import GTK_WORKAREAS_PREFIX
        if prop.startswith(GTK_WORKAREAS_PREFIX):
            # ie: `_GTK_WORKAREAS_D0`, the per-monitor workareas
            method_name = "screen_size_changed"
        else:
            method_name = {
                "_NET_WORKAREA": "screen_size_changed",
                "_NET_CURRENT_DESKTOP": "workspace_changed",
                "_NET_DESKTOP_NAMES": "desktops_changed",
                "_NET_NUMBER_OF_DESKTOPS": "desktops_changed",
            }.get(prop, "")
        if not method_name:
            log.error("Error: unknown property %r", prop)
            return
        handler = getattr(self.display, method_name, noop)
        log("handler(%r)=%s", prop, handler)
        handler("from %r event on %s" % (prop, self._root_props_watcher))

    @staticmethod
    def get_window_stacking(window_client) -> tuple[int, ...]:
        from xpra.x11.xroot_props import root_array_get
        xids = root_array_get("_NET_CLIENT_LIST_STACKING", "window") or ()
        xid_to_wid = {}
        for wid, window in window_client._id_to_window.items():
            gdkwindow = window.get_window()
            if gdkwindow:
                xid_to_wid[gdkwindow.get_xid()] = wid
        stacking = tuple(xid_to_wid[xid] for xid in xids if xid in xid_to_wid)
        log("_NET_CLIENT_LIST_STACKING=%s, window stacking=%s", xids, stacking)
        return stacking
