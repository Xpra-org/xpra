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
    XSettings + root-window property watching (DPI, workarea, desktop names),
    feeding the `display` subsystem (moved from `xpra.platform.posix.client.PlatformClient`).
    This is an X11-binding based, OS/display-server concern, not a toolkit one.
    """

    def __init__(self, display_client):
        self.display = display_client
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
        if self._xsettings_watcher:
            self._xsettings_watcher.cleanup()
            self._xsettings_watcher = None
        if self._root_props_watcher:
            self._root_props_watcher.cleanup()
            self._root_props_watcher = None

    def do_setup_xprops(self, *args) -> None:
        log("do_setup_xprops(%s)", args)
        ROOT_PROPS = ["RESOURCE_MANAGER", "_NET_WORKAREA", "_NET_CURRENT_DESKTOP"]
        try:
            self.init_x11_filter()
            # pylint: disable=import-outside-toplevel
            from xpra.x11.subsystem.xsettings_manager import XSettingsWatcher
            from xpra.x11.xroot_props import XRootPropWatcher
            if self._xsettings_watcher is None:
                self._xsettings_watcher = XSettingsWatcher()
                self._xsettings_watcher.connect("xsettings-changed", self._handle_xsettings_changed)
                self._handle_xsettings_changed()
            if self._root_props_watcher is None:
                self._root_props_watcher = XRootPropWatcher(ROOT_PROPS)
                self._root_props_watcher.connect("root-prop-changed", self._handle_root_prop_changed)
                # ensure we get the initial value:
                self._root_props_watcher.do_notify("RESOURCE_MANAGER")
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

    def _handle_xsettings_changed(self, *_args) -> None:
        settings = self._get_xsettings()
        log("xsettings_changed new value=%s", settings)
        if settings is not None:
            self.display.send("server-settings", {"xsettings-blob": settings})

    def _handle_root_prop_changed(self, obj, prop) -> None:
        log("root_prop_changed(%s, %s)", obj, prop)
        if prop == "RESOURCE_MANAGER":
            rm = get_resource_manager()
            if rm is not None:
                self.display.send("server-settings", {"resource-manager": rm})
            return
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
