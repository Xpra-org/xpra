# This file is part of Xpra.
# Copyright (C) 2010 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2011 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import sys
from typing import Any
from collections.abc import Callable, Sequence

from xpra.os_util import gi_import
from xpra.util.system import is_Wayland, is_X11
from xpra.util.str_fn import csv, bytestostr
from xpra.util.env import envint, envbool, first_time, get_saved_env, get_saved_env_var
from xpra.platform.posix.events import add_handler, remove_handler
from xpra.log import Logger

GLib = gi_import("GLib")

log = Logger("posix")
eventlog = Logger("posix", "events")
screenlog = Logger("posix", "screen")
dbuslog = Logger("posix", "dbus")
traylog = Logger("posix", "tray")
mouselog = Logger("posix", "mouse")
xinputlog = Logger("posix", "xinput")


def x11_bindings():
    if not is_X11():
        return None
    try:
        from xpra.x11 import bindings
        return bindings
    except ImportError as e:
        log("x11_bindings()", exc_info=True)
        from xpra.gtk.util import ds_inited
        if not ds_inited():
            log.warn("Warning: no X11 bindings")
            log.warn(f" {e}")
        return None


def X11WindowBindings():
    xb = x11_bindings()
    if not xb:
        return None
    from xpra.x11.bindings.window import X11WindowBindings  # @UnresolvedImport
    return X11WindowBindings()


def X11RandRBindings():
    xb = x11_bindings()
    if not xb:
        return None
    from xpra.x11.bindings.randr import RandRBindings  # @UnresolvedImport
    return RandRBindings()


def X11XI2Bindings():
    xb = x11_bindings()
    if not xb:
        return None
    from xpra.x11.bindings.xi2 import X11XI2Bindings  # @UnresolvedImport
    return X11XI2Bindings()


device_bell = None
RANDR_DPI = envbool("XPRA_RANDR_DPI", True)
XSETTINGS_DPI = envbool("XPRA_XSETTINGS_DPI", True)
USE_NATIVE_TRAY = envbool("XPRA_USE_NATIVE_TRAY", True)
XINPUT_WHEEL_DIV = envint("XPRA_XINPUT_WHEEL_DIV", 15)


def gl_check() -> str:
    return ""


def get_wm_name() -> str:
    return do_get_wm_name(get_saved_env())


def do_get_wm_name(env) -> str:
    wm_name = env.get("XDG_CURRENT_DESKTOP", "") or env.get("XDG_SESSION_DESKTOP") or env.get("DESKTOP_SESSION")
    if env.get("XDG_SESSION_TYPE") == "wayland" or env.get("GDK_BACKEND") == "wayland":
        if wm_name:
            wm_name += " on wayland"
        else:
            wm_name = "wayland"
    elif is_X11() and x11_bindings():
        from xpra.x11.common import get_wm_name as get_x11_wm_name
        from xpra.gtk.error import xsync
        with xsync:
            wm_name = get_x11_wm_name()
    return wm_name


def get_clipboard_native_class() -> str:
    gtk_clipboard_class = "xpra.gtk.clipboard.GTK_Clipboard"
    if not x11_bindings():
        return gtk_clipboard_class
    try:
        from xpra import x11
        assert x11
    except ImportError:
        return gtk_clipboard_class
    return "xpra.x11.gtk.clipboard.X11Clipboard"


def get_native_system_tray_classes() -> list[type]:
    c = _try_load_appindicator()
    traylog("get_native_system_tray_classes()=%s (USE_NATIVE_TRAY=%s)", c, USE_NATIVE_TRAY)
    return c


def get_native_tray_classes() -> list[type]:
    c = _try_load_appindicator()
    traylog("get_native_tray_classes()=%s (USE_NATIVE_TRAY=%s)", c, USE_NATIVE_TRAY)
    return c


def _try_load_appindicator() -> list[type]:
    if not USE_NATIVE_TRAY:
        return []
    try:
        from xpra.platform.posix.appindicator_tray import AppindicatorTray
        return [AppindicatorTray]
    except (ImportError, ValueError):
        if first_time("no-appindicator"):
            traylog("cannot load appindicator tray", exc_info=True)
            traylog.warn("Warning: appindicator library not found")
            traylog.warn(" you may want to install libappindicator")
            traylog.warn(" to enable the system tray.")
            if get_saved_env_var("XDG_CURRENT_DESKTOP", "").upper().find("GNOME") >= 0:
                traylog.warn(" With gnome-shell, you may also need some extensions:")
                traylog.warn(" 'top icons plus' and / or 'appindicator'")
    return []


def get_native_notifier_classes() -> list[Callable]:
    ncs: list[Callable] = []
    try:
        from xpra.notifications.dbus_notifier import DBUS_Notifier_factory
        ncs.append(DBUS_Notifier_factory)
    except Exception as e:
        dbuslog("cannot load dbus notifier: %s", e)
    try:
        from xpra.notifications.pynotify_notifier import PyNotify_Notifier
        ncs.append(PyNotify_Notifier)
    except Exception as e:
        log("cannot load pynotify notifier: %s", e)
    return ncs


def get_session_type() -> str:
    if is_Wayland():
        return "Wayland"
    if is_X11():
        return "X11"
    return os.environ.get("XDG_SESSION_TYPE", "")


def _get_xsettings():
    if x11_bindings():
        from xpra.gtk.error import xlog
        from xpra.x11.common import get_xsettings
        with xlog:
            return get_xsettings()
    return None


def _get_xsettings_dict() -> dict[str, Any]:
    try:
        from xpra.x11.common import xsettings_to_dict
    except ImportError:
        return {}
    return xsettings_to_dict(_get_xsettings())


def _get_xsettings_dpi() -> int:
    if XSETTINGS_DPI and x11_bindings():
        try:
            from xpra.x11.xsettings_prop import XSettingsType
        except ImportError:
            return -1
        d = _get_xsettings_dict()
        for k, div in {
            "Xft.dpi": 1,
            "Xft/DPI": 1024,
            "gnome.Xft/DPI": 1024,
            # "Gdk/UnscaledDPI" : 1024, ??
        }.items():
            if k in d:
                value_type, value = d.get(k)
                if value_type == XSettingsType.Integer:
                    actual_value = max(10, min(1000, value // div))
                    screenlog("_get_xsettings_dpi() found %s=%s, div=%i, actual value=%i", k, value, div, actual_value)
                    return actual_value
    return -1


def _get_randr_dpi() -> tuple[int, int]:
    if RANDR_DPI and x11_bindings():
        from xpra.x11.common import get_randr_dpi
        from xpra.gtk.error import xlog
        with xlog:
            return get_randr_dpi()
    return -1, -1


def get_xdpi() -> int:
    dpi = _get_xsettings_dpi()
    if dpi > 0:
        return dpi
    return _get_randr_dpi()[0]


def get_ydpi() -> int:
    dpi = _get_xsettings_dpi()
    if dpi > 0:
        return dpi
    return _get_randr_dpi()[1]


def get_icc_info() -> dict[str, Any]:
    if x11_bindings():
        from xpra.x11.common import get_icc_data as get_x11_icc_data
        from xpra.gtk.error import xsync
        with xsync:
            return get_x11_icc_data()
    from xpra.platform.gui import default_get_icc_info
    return default_get_icc_info()


def get_antialias_info() -> dict[str, Any]:
    info: dict[str, Any] = {}
    if not x11_bindings():
        return info
    try:
        from xpra.x11.xsettings_prop import XSettingsType
        d = _get_xsettings_dict()
        for prop_name, name in {
            "Xft/Antialias": "enabled",
            "Xft/Hinting": "hinting",
        }.items():
            if prop_name in d:
                value_type, value = d.get(prop_name)
                if value_type == XSettingsType.Integer and value > 0:
                    info[name] = bool(value)

        def get_contrast(value):
            # win32 API uses numerical values:
            # (this is my best guess at translating the X11 names)
            return {
                "hintnone": 0,
                "hintslight": 1000,
                "hintmedium": 1600,
                "hintfull": 2200,
            }.get(bytestostr(value))

        for prop_name, name, convert in (
                ("Xft/HintStyle", "hintstyle", bytestostr),
                ("Xft/HintStyle", "contrast", get_contrast),
                ("Xft/RGBA", "orientation", lambda x: bytestostr(x).upper())
        ):
            if prop_name in d:
                value_type, value = d.get(prop_name)
                if value_type == XSettingsType.String:
                    cval = convert(value)
                    if cval is not None:
                        info[name] = cval
    except Exception as e:
        screenlog.warn("failed to get antialias info from xsettings: %s", e)
    screenlog("get_antialias_info()=%s", info)
    return info


def get_current_desktop() -> int:
    if x11_bindings():
        from xpra.x11.common import get_current_desktop as get_x11_current_desktop
        from xpra.gtk.error import xsync
        with xsync:
            return get_x11_current_desktop()
    return -1


def get_workarea() -> tuple[int, int, int, int] | None:
    if x11_bindings():
        from xpra.x11.common import get_workarea as get_x11_workarea
        from xpra.gtk.error import xsync
        with xsync:
            return get_x11_workarea()
    return None


def get_number_of_desktops() -> int:
    if x11_bindings():
        from xpra.x11.common import get_number_of_desktops as get_x11_number_of_desktops
        from xpra.gtk.error import xsync
        with xsync:
            return get_x11_number_of_desktops()
    return 0


def get_desktop_names() -> Sequence[str]:
    if x11_bindings():
        from xpra.x11.common import get_desktop_names as get_x11_desktop_names
        from xpra.gtk.error import xsync
        with xsync:
            return get_x11_desktop_names()
    return ("Main", )


def get_vrefresh() -> int:
    if x11_bindings():
        from xpra.x11.common import get_vrefresh as get_x11_vrefresh
        from xpra.gtk.error import xsync
        with xsync:
            return get_x11_vrefresh()
    return -1


def get_cursor_size() -> int:
    if x11_bindings():
        from xpra.x11.common import get_cursor_size as get_x11_cursor_size
        from xpra.gtk.error import xsync
        with xsync:
            return get_x11_cursor_size()
    return -1


def _get_xsettings_int(name: str, default_value: int) -> int:
    d = _get_xsettings_dict()
    if name not in d:
        return default_value
    value_type, value = d.get(name)
    from xpra.x11.xsettings_prop import XSettingsType
    if value_type != XSettingsType.Integer:
        return default_value
    return value


def get_double_click_time() -> int:
    return _get_xsettings_int("Net/DoubleClickTime", -1)


def get_double_click_distance() -> tuple[int, int]:
    v = _get_xsettings_int("Net/DoubleClickDistance", -1)
    return v, v


def get_window_frame_sizes() -> dict[str, Any]:
    # for X11, have to create a window and then check the
    # _NET_FRAME_EXTENTS value after sending a _NET_REQUEST_FRAME_EXTENTS message,
    # so this is done in the gtk client instead of here...
    return {}


def system_bell(*args) -> bool:
    if not x11_bindings():
        return False
    global device_bell
    if device_bell is False:
        # failed already
        return False
    from xpra.gtk.error import XError

    def x11_bell():
        from xpra.x11.common import system_bell as x11_system_bell
        if not x11_system_bell(*args):
            global device_bell
            device_bell = False

    try:
        from xpra.gtk.error import xlog
        with xlog:
            x11_bell()
        return True
    except XError as e:
        log("x11_bell()", exc_info=True)
        log.error("Error using device_bell: %s", e)
        log.error(" switching native X11 bell support off")
        device_bell = False
        return False


def pointer_grab(gdk_window) -> bool:
    if x11_bindings():
        from xpra.gtk.error import xlog
        with xlog:
            return X11WindowBindings().pointer_grab(gdk_window.get_xid())
    return False


def pointer_ungrab(_window) -> bool:
    if x11_bindings():
        from xpra.gtk.error import xlog
        with xlog:
            return X11WindowBindings().UngrabPointer() == 0
    return False


def _send_client_message(window, message_type: str, *values) -> None:
    if not x11_bindings():
        log(f"cannot send client message {message_type} without the X11 bindings")
        return
    from xpra.x11.common import send_client_message
    send_client_message(window, message_type, *values)


def show_desktop(b) -> None:
    _send_client_message(None, "_NET_SHOWING_DESKTOP", int(bool(b)))


def set_fullscreen_monitors(window, fsm, source_indication: int = 0) -> None:
    if not isinstance(fsm, (tuple, list)):
        log.warn("invalid type for fullscreen-monitors: %s", type(fsm))
        return
    if len(fsm) != 4:
        log.warn("invalid number of fullscreen-monitors: %s", len(fsm))
        return
    values = list(fsm) + [source_indication]
    _send_client_message(window, "_NET_WM_FULLSCREEN_MONITORS", *values)


def _toggle_wm_state(window, state, enabled: bool) -> None:
    if enabled:
        action = 1  # "_NET_WM_STATE_ADD"
    else:
        action = 0  # "_NET_WM_STATE_REMOVE"
    _send_client_message(window, "_NET_WM_STATE", action, state)


def set_shaded(window, shaded: bool) -> None:
    _toggle_wm_state(window, "_NET_WM_STATE_SHADED", shaded)


WINDOW_ADD_HOOKS: list[Callable] = []


def add_window_hooks(window) -> None:
    for callback in WINDOW_ADD_HOOKS:
        callback(window)
    log("add_window_hooks(%s) added %s", window, WINDOW_ADD_HOOKS)


WINDOW_REMOVE_HOOKS: list[Callable] = []


def remove_window_hooks(window):
    for callback in WINDOW_REMOVE_HOOKS:
        callback(window)
    log("remove_window_hooks(%s) added %s", window, WINDOW_REMOVE_HOOKS)


def get_info() -> dict[str, Any]:
    from xpra.platform.gui import get_info_base  # pylint: disable=import-outside-toplevel
    i = get_info_base()
    s = _get_xsettings()
    if s:
        serial, values = s
        xi = {"serial": serial}
        for _, name, value, _ in values:
            xi[bytestostr(name)] = value
        i["xsettings"] = xi
    i.setdefault("dpi", {
        "xsettings": _get_xsettings_dpi(),
        "randr": _get_randr_dpi()
    })
    return i


def suppress_event(*_args) -> None:
    """ we'll use XI2 to receive events """


class XI2_Window:
    def __init__(self, window):
        log("XI2_Window(%s)", window)
        self.XI2 = X11XI2Bindings()
        self.X11Window = X11WindowBindings()
        self.window = window
        self.xid = window.get_window().get_xid()
        self.windows: Sequence[int] = ()
        self.motion_valuators = {}
        window.connect("configure-event", self.configured)
        self.configured()
        # replace event handlers with XI2 version:
        self._do_motion_notify_event = window._do_motion_notify_event
        window._do_motion_notify_event = suppress_event
        window._do_button_press_event = suppress_event
        window._do_button_release_event = suppress_event
        window._do_scroll_event = suppress_event
        window.connect("destroy", self.cleanup)

    def cleanup(self, *_args) -> None:
        for window in self.windows:
            self.XI2.disconnect(window)
        self.windows = ()
        self.window = None

    def configured(self, *_args) -> None:
        from xpra.gtk.error import xlog
        with xlog:
            self.windows = self.get_parent_windows(self.xid)
        for window in (self.windows or ()):
            self.XI2.connect(window, "XI_Motion", self.do_xi_motion)
            self.XI2.connect(window, "XI_ButtonPress", self.do_xi_button)
            self.XI2.connect(window, "XI_ButtonRelease", self.do_xi_button)
            self.XI2.connect(window, "XI_DeviceChanged", self.do_xi_device_changed)
            self.XI2.connect(window, "XI_HierarchyChanged", self.do_xi_hierarchy_changed)

    def do_xi_device_changed(self, *_args) -> None:
        self.motion_valuators = {}

    def do_xi_hierarchy_changed(self, *_args) -> None:
        self.motion_valuators = {}

    def get_parent_windows(self, oxid: int) -> Sequence[int]:
        windows = [oxid]
        root = self.X11Window.get_root_xid()
        xid = oxid
        while True:
            xid = self.X11Window.getParent(xid)
            if xid == 0 or xid == root:
                break
            windows.append(xid)
        xinputlog("get_parent_windows(%#x)=%s", oxid, csv(hex(x) for x in windows))
        return tuple(windows)

    def do_xi_button(self, event, device) -> None:
        window = self.window
        client = window._client
        if client.readonly:
            return
        xinputlog("do_xi_button(%s, %s) server_input_devices=%s", event, device, client.server_input_devices)
        if client.server_input_devices == "xi" or (
                client.server_input_devices == "uinput" and client.server_precise_wheel):
            # skip synthetic scroll events,
            # as the server should synthesize them from the motion events
            # those have the same serial:
            matching_motion = self.XI2.find_event("XI_Motion", event.serial)
            # maybe we need more to distinguish?
            if matching_motion:
                return
        button = event.detail
        depressed = (event.name == "XI_ButtonPress")
        props = self.get_pointer_extra_args(event)
        window._button_action(button, event, depressed, props)

    def do_xi_motion(self, event, device) -> None:
        window = self.window
        if window.moveresize_event:
            xinputlog("do_xi_motion(%s, %s) handling as a moveresize event on window %s", event, device, window)
            window.motion_moveresize(event)
            self._do_motion_notify_event(event)
            return
        client = window._client
        if client.readonly:
            return
        pointer_data, modifiers, buttons = window._pointer_modifiers(event)
        wid = self.window.get_mouse_event_wid(*pointer_data)
        # log("server_input_devices=%s, server_precise_wheel=%s",
        #    client.server_input_devices, client.server_precise_wheel)
        valuators = event.valuators
        unused_valuators = valuators.copy()
        dx, dy = 0, 0
        if (
                valuators and device and device.get("enabled")
                and client.server_input_devices == "uinput"  # noqa W503
                and client.server_precise_wheel  # noqa W503
        ):
            XIModeRelative = 0
            classes = device.get("classes")
            val_classes = {}
            for c in classes.values():
                number = c.get("number")
                if number is not None and c.get("type") == "valuator" and c.get("mode") == XIModeRelative:
                    val_classes[number] = c
            # previous values:
            mv = self.motion_valuators.setdefault(event.device, {})
            last_x, last_y = 0, 0
            wheel_x, wheel_y = 0, 0
            unused_valuators = {}
            for number, value in valuators.items():
                valuator = val_classes.get(number)
                if valuator:
                    label = valuator.get("label")
                    if label:
                        mouselog("%s: %s", label, value)
                        if label.lower().find("horiz") >= 0:
                            wheel_x = value
                            last_x = mv.get(number)
                            continue
                        elif label.lower().find("vert") >= 0:
                            wheel_y = value
                            last_y = mv.get(number)
                            continue
                unused_valuators[number] = value
            # new absolute motion values:
            # calculate delta if we have both old and new values:
            if last_x is not None and wheel_x is not None:
                dx = last_x - wheel_x
            if last_y is not None and wheel_y is not None:
                dy = last_y - wheel_y
            # whatever happens, update our motion cached values:
            mv.update(event.valuators)
        # send plain motion first, if any:
        props = self.get_pointer_extra_args(event)
        if unused_valuators:
            xinputlog("do_xi_motion(%s, %s) wid=%s / focus=%s / window wid=%i",
                      event, device, wid, window._client._focused, window.wid)
            xinputlog(" device=%s, pointer=%s, modifiers=%s, buttons=%s",
                      event.device, pointer_data, modifiers, buttons)
            device_id = 0
            client.send_mouse_position(device_id, wid, pointer_data, modifiers, buttons, props)
        # now see if we have anything to send as a wheel event:
        if dx != 0 or dy != 0:
            xinputlog("do_xi_motion(%s, %s) wheel deltas: dx=%i, dy=%i", event, device, dx, dy)
            # normalize (xinput is always using 15 degrees?)
            client.wheel_event(event.device, wid, dx / XINPUT_WHEEL_DIV, dy / XINPUT_WHEEL_DIV, pointer_data, props)

    def get_pointer_extra_args(self, event) -> dict[str, Any]:
        def intscaled(f):
            return int(f * 1000000), 1000000

        def dictscaled(d):
            return {k: intscaled(v) for k, v in d.items()}

        props = {
            "device": event.device,
        }
        for k in ("x", "y", "x_root", "y_root"):
            props[k] = intscaled(getattr(event, k))
        props["valuators"] = dictscaled(event.valuators or {})
        raw_event_name = event.name.replace("XI_", "XI_Raw")  # ie: XI_Motion -> XI_RawMotion
        raw = self.XI2.find_event(raw_event_name, event.serial)
        props["raw-valuators"] = dictscaled(raw.raw_valuators if raw else {})
        return props


class ClientExtras:
    def __init__(self, client, _opts):
        self.client = client
        self._xsettings_watcher = None
        self._root_props_watcher = None
        self.x11_filter = None
        if client.xsettings_enabled:
            self.setup_xprops()
        self.xi_setup_failures = 0
        input_devices = getattr(client, "input_devices", None)
        if input_devices in ("xi", "auto"):
            # this would trigger warnings with our temporary opengl windows:
            # only enable it after we have connected:
            client.after_handshake(self.setup_xi)
        self.setup_dbus_signals()

    def ready(self) -> None:
        """ unused on posix """

    def init_x11_filter(self) -> None:
        if self.x11_filter:
            return
        try:
            from xpra.x11.gtk.bindings import init_x11_filter  # @UnresolvedImport, @UnusedImport
            self.x11_filter = init_x11_filter()
            log("x11_filter=%s", self.x11_filter)
        except Exception as e:
            log("init_x11_filter()", exc_info=True)
            log.error("Error: failed to initialize X11 GDK filter:")
            log.estr(e)
            self.x11_filter = None

    def cleanup(self) -> None:
        log("cleanup() xsettings_watcher=%s, root_props_watcher=%s", self._xsettings_watcher, self._root_props_watcher)
        if self.x11_filter:
            self.x11_filter = None
            from xpra.x11.gtk.bindings import cleanup_x11_filter  # @UnresolvedImport, @UnusedImport
            cleanup_x11_filter()
        if self._xsettings_watcher:
            self._xsettings_watcher.cleanup()
            self._xsettings_watcher = None
        if self._root_props_watcher:
            self._root_props_watcher.cleanup()
            self._root_props_watcher = None
        remove_handler("suspend", self.suspend_callback)
        remove_handler("resume", self.resume_callback)

    def suspend_callback(self, *args) -> None:
        eventlog("suspend_callback%s", args)
        if self.client:
            self.client.suspend()

    def resume_callback(self, *args) -> None:
        eventlog("resume_callback%s", args)
        if self.client:
            self.client.resume()

    def setup_dbus_signals(self) -> None:
        add_handler("suspend", self.suspend_callback)
        add_handler("resume", self.resume_callback)

    def setup_xprops(self) -> None:
        # wait for handshake to complete:
        if x11_bindings() and self.client:
            self.client.after_handshake(self.do_setup_xprops)

    def do_setup_xprops(self, *args) -> None:
        log("do_setup_xprops(%s)", args)
        ROOT_PROPS = ["RESOURCE_MANAGER", "_NET_WORKAREA", "_NET_CURRENT_DESKTOP"]
        try:
            self.init_x11_filter()
            # pylint: disable=import-outside-toplevel
            from xpra.x11.xsettings import XSettingsWatcher
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
        XI2 = X11XI2Bindings()
        devices = XI2.get_devices()
        if devices:
            self.client.send_input_devices("xi", devices)

    def setup_xi(self) -> None:
        GLib.timeout_add(100, self.do_setup_xi)

    def do_setup_xi(self) -> bool:
        if self.client.server_input_devices not in ("xi", "uinput"):
            xinputlog("server does not support xi input devices")
            if self.client.server_input_devices:
                log(" server uses: %s", self.client.server_input_devices)
            return False
        try:
            from xpra.gtk.error import xsync, XError  # pylint: disable=import-outside-toplevel
            assert X11WindowBindings(), "no X11 window bindings"
            XI2 = X11XI2Bindings()
            assert XI2, "no XI2 window bindings"
            # this may fail when windows are being destroyed,
            # ie: when another client disconnects because we are stealing the session
            try:
                with xsync:
                    XI2.select_xi2_events()
            except XError:
                self.xi_setup_failures += 1
                xinputlog("select_xi2_events() failed, attempt %i",
                          self.xi_setup_failures, exc_info=True)
                return self.xi_setup_failures < 10  # try again
            with xsync:
                XI2.gdk_inject()
                self.init_x11_filter()
                if self.client.server_input_devices:
                    XI2.connect(0, "XI_HierarchyChanged", self.do_xi_devices_changed)
                    devices = XI2.get_devices()
                    if devices:
                        self.client.send_input_devices("xi", devices)
        except Exception as e:
            xinputlog("enable_xi2()", exc_info=True)
            xinputlog.error("Error: cannot enable XI2 events")
            xinputlog.estr(e)
        else:
            # register our enhanced event handlers:
            self.add_xi2_method_overrides()
        return False

    def add_xi2_method_overrides(self) -> None:
        global WINDOW_ADD_HOOKS
        WINDOW_ADD_HOOKS = [XI2_Window]

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
            self.client.send("server-settings", {"xsettings-blob": settings})

    def get_resource_manager(self):
        try:
            from xpra.gtk.util import get_default_root_window
            from xpra.x11.gtk.prop import prop_get
            root = get_default_root_window()
            xid = root.get_xid()
            value = prop_get(xid, "RESOURCE_MANAGER", "latin1", ignore_errors=True)
            if value is not None:
                return value.encode("utf-8")
        except (ImportError, UnicodeEncodeError):
            log.error("failed to get RESOURCE_MANAGER", exc_info=True)
        return None

    def _handle_root_prop_changed(self, obj, prop) -> None:
        log("root_prop_changed(%s, %s)", obj, prop)
        if prop == "RESOURCE_MANAGER":
            rm = self.get_resource_manager()
            if rm is not None:
                self.client.send("server-settings", {"resource-manager": rm})
        elif prop == "_NET_WORKAREA":
            self.client.screen_size_changed("from %s event" % self._root_props_watcher)
        elif prop == "_NET_CURRENT_DESKTOP":
            self.client.workspace_changed("from %s event" % self._root_props_watcher)
        elif prop in ("_NET_DESKTOP_NAMES", "_NET_NUMBER_OF_DESKTOPS"):
            self.client.desktops_changed("from %s event" % self._root_props_watcher)
        else:
            log.error("unknown property %s", prop)


def main() -> int:
    try:
        from xpra.x11.gtk.display_source import init_gdk_display_source
        init_gdk_display_source()
    except ImportError:
        pass
    from xpra.platform.gui import main as gui_main
    gui_main()
    return 0


if __name__ == "__main__":
    sys.exit(main())
