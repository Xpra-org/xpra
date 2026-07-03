# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.client.base.stub import StubClientSubsystem
from xpra.os_util import gi_import
from xpra.util.system import is_Wayland
from xpra.log import Logger, is_debug_enabled

GLib = gi_import("GLib")

log = Logger("posix")
xinputlog = Logger("posix", "xinput")


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


class XI2Client(StubClientSubsystem):
    """
    XI2 input device enumeration + hierarchy-change events, feeding the
    `window` subsystem's `WindowPointer` leaf. Only composed on POSIX
    (excluding OSX) when the `window` and `pointer` subsystems are both
    enabled - see `xpra.client.gui.factory.get_client_subsystems`.
    """
    PREFIX = "xi2"

    def __init__(self, client=None):
        StubClientSubsystem.__init__(self, client)
        self._x11_filter = None
        self._xi_setup_failures = 0

    def init(self, opts) -> None:
        # this would trigger warnings with our temporary opengl windows:
        # only enable it once we have connected:
        self.client.after_handshake(self.setup_xi)

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
        if self._x11_filter:
            self._x11_filter = None
            from xpra.x11.gtk.bindings import cleanup_x11_filter  # @UnresolvedImport, @UnusedImport
            cleanup_x11_filter()

    def do_xi_devices_changed(self, event) -> None:
        log("do_xi_devices_changed(%s)", event)
        self.send_xi2_devices()

    def send_xi2_devices(self) -> None:
        from xpra.x11.bindings.xi2 import X11XI2Bindings  # @UnresolvedImport
        XI2 = X11XI2Bindings()
        devices = XI2.get_devices()
        if devices:
            window = self.get_subsystem("window")
            window.send_input_devices("xi", devices)

    def setup_xi(self) -> None:
        GLib.timeout_add(100, self.do_setup_xi)

    def do_setup_xi(self) -> bool:
        window = self.get_subsystem("window")
        input_devices = window.input_devices
        server_input_devices = window.server_input_devices or ""

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
            from xpra.platform.posix.gui import X11WindowBindings
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
