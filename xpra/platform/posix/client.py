# This file is part of Xpra.
# Copyright (C) 2025 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.client.base.stub import StubClientMixin
from xpra.platform.posix.gui import x11_bindings, X11WindowBindings
from xpra.util.parsing import str_to_bool
from xpra.common import noop
from xpra.os_util import OSX, WIN32, gi_import
from xpra.log import Logger, is_debug_enabled
from xpra.util.system import is_Wayland

GLib = gi_import("GLib")

log = Logger("posix")
eventlog = Logger("posix", "events")
xinputlog = Logger("posix", "xinput")


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


def add_xi2_method_overrides() -> None:
    from xpra.platform.posix.gui import WINDOW_ADD_HOOKS
    from xpra.platform.posix.xi2 import XI2_Window
    if XI2_Window not in WINDOW_ADD_HOOKS:
        WINDOW_ADD_HOOKS.append(XI2_Window)


def xi2_debug() -> None:
    # adds the xi2 event names to X11 event logger:
    if not is_debug_enabled("x11"):
        return
    try:
        from xpra.x11.bindings.xi2 import init_xi2_events
        init_xi2_events(False)
    except ImportError:
        xinputlog("xi2_debug()", exc_info=True)


class PlatformClient(StubClientMixin):
    def __init__(self):
        self._xsettings_enabled = False
        self._xsettings_watcher = None
        self._root_props_watcher = None
        self._x11_filter = None
        self._xi_setup_failures = 0

    def init(self, opts) -> None:
        self._xsettings_enabled = not (OSX or WIN32 or is_Wayland()) and str_to_bool(opts.xsettings)
        if self._xsettings_enabled:
            self.setup_xprops()

    def init_ui(self, opts) -> None:
        # this would trigger warnings with our temporary opengl windows:
        # only enable it after we have connected:
        self.after_handshake(self.setup_xi)

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

    def suspend_callback(self, *args) -> None:
        eventlog("suspend_callback%s", args)
        self.suspend()

    def resume_callback(self, *args) -> None:
        eventlog("resume_callback%s", args)
        self.resume()

    def setup_xprops(self) -> None:
        # wait for handshake to complete:
        if x11_bindings():
            self.after_handshake(self.do_setup_xprops)

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

    def do_xi_devices_changed(self, event) -> None:
        log("do_xi_devices_changed(%s)", event)
        self.send_xi2_devices()

    def send_xi2_devices(self) -> None:
        from xpra.x11.bindings.xi2 import X11XI2Bindings  # @UnresolvedImport
        XI2 = X11XI2Bindings()
        devices = XI2.get_devices()
        # the optional `send_input_devices` method belongs in the `WindowsClient`:
        send_input_devices = getattr(self, "send_input_devices", noop)
        if devices:
            send_input_devices("xi", devices)

    def setup_xi(self) -> None:
        GLib.timeout_add(100, self.do_setup_xi)

    def do_setup_xi(self) -> bool:
        # the optional `input_devices` and `server_input_devices` attributes belong in the `WindowsClient`:
        input_devices = getattr(self, "input_devices", "")
        server_input_devices = getattr(self, "server_input_devices", "")

        if input_devices.lower() in ("noxi2", "nox"):
            return False

        if input_devices == "auto" and is_Wayland():
            return False

        if input_devices not in ("xi", "auto"):
            xi2_debug()
            return False

        if server_input_devices not in ("xi", "uinput"):
            xinputlog("server does not support xi input devices")
            if server_input_devices:
                log(" server uses: %r", server_input_devices)
            xi2_debug()
            return False

        try:
            from xpra.x11.error import xsync, XError  # pylint: disable=import-outside-toplevel
            from xpra.x11.bindings.xi2 import X11XI2Bindings  # @UnresolvedImport
            assert X11WindowBindings(), "no X11 window bindings"
            XI2 = X11XI2Bindings()
            # this may fail when windows are being destroyed,
            # ie: when another client disconnects because we are stealing the session
            try:
                with xsync:
                    XI2.select_xi2_events()
            except XError:
                self._xi_setup_failures += 1
                xinputlog("select_xi2_events() failed, attempt %i",
                          self._xi_setup_failures, exc_info=True)
                return self._xi_setup_failures < 10  # try again
            with xsync:
                XI2.gdk_inject()
                self.init_x11_filter()
                if server_input_devices:
                    XI2.connect(0, "XI_HierarchyChanged", self.do_xi_devices_changed)
                    self.send_xi2_devices()
        except Exception as e:
            xinputlog("enable_xi2()", exc_info=True)
            xinputlog.error("Error: cannot enable XI2 events")
            xinputlog.estr(e)
        else:
            # register our enhanced event handlers:
            add_xi2_method_overrides()
        return False

    def _get_xsettings(self):
        xw = self._xsettings_watcher
        if xw:
            with log.trap_error("Error retrieving XSETTINGS"):
                return xw.get_settings()
        return None

    def _handle_xsettings_changed(self, *_args) -> None:
        settings = self._get_xsettings()
        log("xsettings_changed new value=%s", settings)
        if settings is not None:
            self.send("server-settings", {"xsettings-blob": settings})

    def _handle_root_prop_changed(self, obj, prop) -> None:
        log("root_prop_changed(%s, %s)", obj, prop)
        if prop == "RESOURCE_MANAGER":
            rm = get_resource_manager()
            if rm is not None:
                self.send("server-settings", {"resource-manager": rm})
            return
        # check that our client class has the methods: `screen_size_changed`, etc:
        try:
            from xpra.client.subsystem.display import DisplayClient
        except ImportError:
            return
        if not isinstance(self, DisplayClient):
            return
        if prop == "_NET_WORKAREA":
            self.screen_size_changed("from %s event" % self._root_props_watcher)
        elif prop == "_NET_CURRENT_DESKTOP":
            self.workspace_changed("from %s event" % self._root_props_watcher)
        elif prop in ("_NET_DESKTOP_NAMES", "_NET_NUMBER_OF_DESKTOPS"):
            self.desktops_changed("from %s event" % self._root_props_watcher)
        else:
            log.error("unknown property %s", prop)
