# This file is part of Xpra.
# Copyright (C) 2011 Serviware (Arthur Huillet, <ahuillet@serviware.com>)
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
from typing import Any
from collections.abc import Callable

from xpra.os_util import gi_import
from xpra.util.str_fn import strtobytes, bytestostr, hexstr
from xpra.util.objects import typedict
from xpra.util.env import envbool
from xpra.gtk.error import xswallow, xsync, xlog
from xpra.scripts.config import str_to_bool
from xpra.server import ServerExitMode
from xpra.common import SYNC_ICC
from xpra.server import features
from xpra.x11.server.core import X11ServerCore, XTestPointerDevice
from xpra.x11.bindings.keyboard import X11KeyboardBindings
from xpra.x11.gtk.prop import prop_set, prop_del
from xpra.x11.xsettings_prop import XSettingsType, BLOCKLISTED_XSETTINGS
from xpra.log import Logger

GLib = gi_import("GLib")

log = Logger("x11", "server")
mouselog = Logger("x11", "server", "mouse")
screenlog = Logger("server", "screen")
dbuslog = Logger("dbus")

X11Keyboard = X11KeyboardBindings()

SCALED_FONT_ANTIALIAS = envbool("XPRA_SCALED_FONT_ANTIALIAS", False)


def root_prop_set(prop_name: str, prop_type: list | tuple | str, value) -> None:
    # pylint: disable=import-outside-toplevel
    prop_set(X11Keyboard.get_root_xid(), prop_name, prop_type, value)


def root_prop_del(prop_name: str) -> None:
    prop_del(X11Keyboard.get_root_xid(), prop_name)


def _get_antialias_hintstyle(antialias: typedict) -> str:
    hintstyle = antialias.strget("hintstyle").lower()
    if hintstyle in ("hintnone", "hintslight", "hintmedium", "hintfull"):
        # X11 clients can give us what we need directly:
        return hintstyle
    # win32 style contrast value:
    contrast = antialias.intget("contrast", -1)
    if contrast > 1600:
        return "hintfull"
    if contrast > 1000:
        return "hintmedium"
    if contrast > 0:
        return "hintslight"
    return "hintnone"


class X11ServerBase(X11ServerCore):
    """
        Base class for X11 servers,
        adds uinput, icc and xsettings synchronization to the X11ServerCore class
        (see XpraServer or DesktopServer for actual implementations)
    """

    def __init__(self):
        super().__init__()
        self._default_xsettings: tuple[int, list[tuple]] = (0, [])
        self._settings: dict[str, Any] = {}
        self._xsettings_manager = None
        self._xsettings_enabled: bool = False
        self.display_pid: int = 0
        self.icc_profile: bytes = b""
        self.input_devices = "xtest"

    def do_init(self, opts) -> None:
        super().do_init(opts)
        # the server class sets the default value for 'xsettings_enabled'
        # it is overridden in the seamless server (enabled by default),
        # and we let the options have the final say here:
        self._xsettings_enabled = str_to_bool(opts.xsettings, self._xsettings_enabled)
        log("xsettings_enabled(%s)=%s", opts.xsettings, self._xsettings_enabled)
        if self._xsettings_enabled:
            from xpra.x11.xsettings import XSettingsHelper
            self._default_xsettings = XSettingsHelper().get_settings()
            log("_default_xsettings=%s", self._default_xsettings)
            self.init_all_server_settings()

    # noinspection PyMethodMayBeStatic
    def save_pid(self) -> None:
        root_prop_set("XPRA_SERVER_PID", "u32", os.getpid())

    def clean_x11_properties(self) -> None:
        super().clean_x11_properties()
        self.do_clean_x11_properties("XPRA_SERVER_PID")

    def init_display_pid(self, pid: int) -> None:
        if not pid:
            log.info("xvfb pid not found")
        else:
            log.info(f"xvfb pid {pid}")
        self.display_pid = pid

    def kill_display(self) -> None:
        if self.display_pid:
            if self._exit_mode in (ServerExitMode.UPGRADE, ServerExitMode.EXIT):
                action = "exiting" if self._exit_mode == ServerExitMode.EXIT else "upgrading"
                log.info(f"{action}: not cleaning up Xvfb")
                return
            from xpra.x11.vfb_util import kill_xvfb
            kill_xvfb(self.display_pid)
            self.do_clean_session_files(
                "xvfb.pid",
                "xauthority",
                "Xorg.log",
                "Xorg.log.old",
                "xorg.conf.d/*"
                "xorg.conf.d"
            )

    def late_cleanup(self, stop=True) -> None:
        self.kill_display()
        super().late_cleanup(stop)

    def configure_best_screen_size(self) -> tuple[int, int]:
        root_w, root_h = super().configure_best_screen_size()
        if self.touchpad_device:
            self.touchpad_device.root_w = root_w
            self.touchpad_device.root_h = root_h
        return root_w, root_h

    def init_dbus(self, dbus_pid: int, dbus_env: dict[str, str]) -> None:
        dbuslog("init_dbus(%s, %s)", dbus_pid, dbus_env)
        if dbus_pid and dbus_env:
            os.environ.update(dbus_env)
            self.dbus_pid = dbus_pid
            self.dbus_env = dbus_env

            # now we can save values on the display
            # (we cannot access bindings until dbus has started up)

            def _save_int(prop_name, intval) -> None:
                root_prop_set(prop_name, "u32", intval)

            def _save_str(prop_name, strval) -> None:
                root_prop_set(prop_name, "latin1", strval)

            # DBUS_SESSION_BUS_ADDRESS=unix:abstract=/tmp/dbus-B8CDeWmam9,guid=b77f682bd8b57a5cc02f870556cbe9e9
            # DBUS_SESSION_BUS_PID=11406
            # DBUS_SESSION_BUS_WINDOWID=50331649
            attributes: list[tuple[str, type, Callable[[str, int | str], None]]] = [
                ("ADDRESS", str, _save_str),
                ("PID", int, _save_int),
                ("WINDOW_ID", int, _save_int),
            ]
            for name, conv, save in attributes:
                k = f"DBUS_SESSION_BUS_{name}"
                v = dbus_env.get(k, "")
                if not v:
                    continue
                try:
                    tv = conv(v)
                    save(k, tv)
                except Exception as e:
                    log("save_dbus_env(%s)", dbus_env, exc_info=True)
                    log.error(f"Error: failed to save dbus environment variable {k!r}")
                    log.error(f" with value {v!r}")
                    log.estr(e)

    def last_client_exited(self) -> None:
        self.reset_settings()
        super().last_client_exited()

    def init_virtual_devices(self, devices: dict[str, Any]) -> None:
        # pylint: disable=import-outside-toplevel
        # (this runs in the main thread - before the main loop starts)
        # for the time being, we only use the pointer if there is one:
        pointer = devices.get("pointer")
        touchpad = devices.get("touchpad")
        mouselog("init_virtual_devices(%s) got pointer=%s, touchpad=%s", devices, pointer, touchpad)
        self.input_devices = "xtest"
        if pointer:
            uinput_device = pointer.get("uinput")
            device_path = pointer.get("device")
            if uinput_device:
                from xpra.x11.uinput_device import UInputPointerDevice
                self.input_devices = "uinput"
                self.pointer_device = UInputPointerDevice(uinput_device, device_path)
                self.verify_uinput_pointer_device()
        if self.input_devices == "uinput" and touchpad:
            uinput_device = touchpad.get("uinput")
            device_path = touchpad.get("device")
            if uinput_device:
                from xpra.x11.uinput_device import UInputTouchpadDevice
                root_w, root_h = self.get_root_window_size()
                self.touchpad_device = UInputTouchpadDevice(uinput_device, device_path, root_w, root_h)
        try:
            mouselog.info("pointer device emulation using %s", str(self.pointer_device).replace("PointerDevice", ""))
        except Exception as e:
            mouselog("cannot get pointer device class from %s: %s", self.pointer_device, e)

    def verify_uinput_pointer_device(self) -> None:
        xtest = XTestPointerDevice()
        ox, oy = 100, 100
        with xlog:
            xtest.move_pointer(ox, oy)
        nx, ny = 200, 200
        self.pointer_device.move_pointer(nx, ny)

        def verify_uinput_moved() -> None:
            pos = (ox, oy)
            with xswallow:
                pos = X11Keyboard.query_pointer()
                mouselog("X11Keyboard.query_pointer=%s", pos)
            if pos == (ox, oy):
                mouselog.warn("Warning: %s failed verification", self.pointer_device)
                mouselog.warn(" expected pointer at %s, now at %s", (nx, ny), pos)
                mouselog.warn(" using XTest fallback")
                self.pointer_device = xtest
                self.input_devices = "xtest"

        GLib.timeout_add(1000, verify_uinput_moved)

    def dpi_changed(self) -> None:
        # re-apply the same settings, which will apply the new dpi override to it:
        self.update_server_settings()

    def get_info(self, proto=None, client_uuids=None) -> dict[str, Any]:
        info = super().get_info(proto=proto, client_uuids=client_uuids)
        display_info = info.setdefault("display", {})
        if self.display_pid:
            display_info["pid"] = self.display_pid
        display_info["icc"] = self.get_icc_info()
        return info

    def get_icc_info(self) -> dict[str, Any]:
        icc_info: dict[str, Any] = {
            "sync": SYNC_ICC,
        }
        if SYNC_ICC:
            icc_info["profile"] = hexstr(self.icc_profile)
        return icc_info

    def set_icc_profile(self) -> None:
        if not SYNC_ICC:
            return
        ui_clients = [s for s in self._server_sources.values() if s.ui_client]
        if len(ui_clients) != 1:
            screenlog("%i UI clients, resetting ICC profile to default", len(ui_clients))
            self.reset_icc_profile()
            return
        icc = typedict(ui_clients[0].icc)
        for x in ("data", "icc-data", "icc-profile"):
            data = icc.bytesget(x)
            if data:
                screenlog("set_icc_profile() icc data for %s: %s (%i bytes)",
                          ui_clients[0], hexstr(data), len(data))
                self.icc_profile = data
                root_prop_set("_ICC_PROFILE", ["u32"], data)
                root_prop_set("_ICC_PROFILE_IN_X_VERSION", "u32", 0 * 100 + 4)  # 0.4 -> 0*100+4*1
                return
        screenlog("no icc data found in %s", icc)
        self.reset_icc_profile()

    def reset_icc_profile(self) -> None:
        screenlog("reset_icc_profile()")
        root_prop_del("_ICC_PROFILE")
        root_prop_del("_ICC_PROFILE_IN_X_VERSION")
        self.icc_profile = b""

    def reset_settings(self) -> None:
        if not self._xsettings_enabled:
            return
        log("resetting xsettings to: %s", self._default_xsettings)
        self.set_xsettings(self._default_xsettings or (0, ()))

    def set_xsettings(self, v) -> None:
        if not self._xsettings_enabled:
            return
        log("set_xsettings(%s)", v)
        with xsync:
            if self._xsettings_manager is None:
                from xpra.x11.xsettings import XSettingsManager
                self._xsettings_manager = XSettingsManager()
            self._xsettings_manager.set_settings(v)

    def init_all_server_settings(self) -> None:
        if not features.display:
            return
        log("init_all_server_settings() dpi=%i, default_dpi=%i", self.dpi, self.default_dpi)
        # almost like update_all, except we use the default_dpi,
        # since this is called before the first client connects
        self.do_update_server_settings(
            {
                "resource-manager": b"",
                "xsettings-blob": (0, [])
            }, reset=True, dpi=self.default_dpi, cursor_size=24)

    def update_all_server_settings(self, reset=False) -> None:
        self.update_server_settings(
            {
                "resource-manager": b"",
                "xsettings-blob": (0, []),
            }, reset=reset)

    def update_server_settings(self, settings=None, reset=False) -> None:
        if not features.display:
            return
        cursor_size = getattr(self, "cursor_size", 0)
        dpi = getattr(self, "dpi", 0)
        antialias = getattr(self, "antialias", {})
        double_click_time = getattr(self, "double_click_time", 0)
        double_click_distance = getattr(self, "double_click_distance", (-1, -1))
        self.do_update_server_settings(settings or self._settings, reset,
                                       dpi, double_click_time, double_click_distance,
                                       antialias, cursor_size)

    def do_update_server_settings(self, settings, reset=False,
                                  dpi=0, double_click_time=0, double_click_distance=(-1, -1),
                                  antialias=None, cursor_size=-1) -> None:
        if not self._xsettings_enabled:
            log(f"ignoring xsettings update: {settings}")
            return
        if reset:
            # FIXME: preserve serial? (what happens when we change values which had the same serial?)
            self.reset_settings()
            self._settings = {}
            if self._default_xsettings:
                # try to parse default xsettings into a dict:
                try:
                    for _, prop_name, value, _ in self._default_xsettings[1]:
                        self._settings[prop_name] = value
                except Exception as e:
                    log(f"failed to parse {self._default_xsettings}")
                    log.warn("Warning: failed to parse default XSettings:")
                    log.warn(f" {e}")
        old_settings = dict(self._settings)
        log("server_settings: old=%r, updating with=%r", old_settings, settings)
        log("overrides: ")
        log(f" {dpi=}")
        log(f" {double_click_time=}, {double_click_distance=}")
        log(f" {antialias=}")
        # older versions may send keys as "bytes":
        settings = {bytestostr(k): v for k, v in settings.items()}
        self._settings.update(settings)
        for k, v in settings.items():
            # cook the "resource-manager" value to add the DPI and/or antialias values:
            if k == "resource-manager" and (dpi > 0 or antialias or cursor_size > 0):
                value = bytestostr(v)
                # parse the resources into a dict:
                values = {}
                options = value.split("\n")
                for option in options:
                    if not option:
                        continue
                    parts = option.split(":\t", 1)
                    if len(parts) != 2:
                        log(f"skipped invalid option: {option!r}")
                        continue
                    if parts[0] in BLOCKLISTED_XSETTINGS:
                        log(f"skipped blocklisted option: {option!r}")
                        continue
                    values[parts[0]] = parts[1]
                if cursor_size > 0:
                    values["Xcursor.size"] = cursor_size
                if dpi > 0:
                    values["Xft.dpi"] = dpi
                    values["Xft/DPI"] = dpi * 1024
                    values["gnome.Xft/DPI"] = dpi * 1024
                if antialias:
                    ad = typedict(antialias)
                    subpixel_order = "none"
                    sss = tuple(self._server_sources.values())
                    if len(sss) == 1:
                        # only honour sub-pixel hinting if a single client is connected
                        # and only when it is not using any scaling (or overridden with SCALED_FONT_ANTIALIAS):
                        ss = sss[0]
                        ds_unscaled = getattr(ss, "desktop_size_unscaled", None)
                        ds_scaled = getattr(ss, "desktop_size", None)
                        if SCALED_FONT_ANTIALIAS or (not ds_unscaled or ds_unscaled == ds_scaled):
                            subpixel_order = ad.strget("orientation", "none").lower()
                    values |= {
                        "Xft.antialias": ad.intget("enabled", -1),
                        "Xft.hinting": ad.intget("hinting", -1),
                        "Xft.rgba": subpixel_order,
                        "Xft.hintstyle": _get_antialias_hintstyle(ad),
                    }
                log(f"server_settings: resource-manager {values=}")
                # convert the dict back into a resource string:
                value = ''
                for vk, vv in values.items():
                    value += f"{vk}:\t{vv}\n"
                # record the actual value used
                self._settings["resource-manager"] = value
                v = value.encode("utf-8")

            # cook xsettings to add various settings:
            # (as those may not be present in xsettings on some platforms… like win32 and osx)
            have_override = self.double_click_time > 0 or self.double_click_distance != (-1, -1) or antialias or dpi > 0
            if k == "xsettings-blob" and have_override:
                # start by removing blocklisted options:
                def filter_blocklisted():
                    serial, values = v
                    new_values = []
                    for _t, _n, _v, _s in values:
                        if bytestostr(_n) in BLOCKLISTED_XSETTINGS:
                            log("skipped blocklisted option %s", (_t, _n, _v, _s))
                        else:
                            new_values.append((_t, _n, _v, _s))
                    return serial, new_values

                v = filter_blocklisted()

                def set_xsettings_value(name, value_type, value):
                    # remove existing one, if any:
                    serial, values = v
                    bn = name.encode("utf-8")
                    new_values = [(_t, _n, _v, _s) for (_t, _n, _v, _s) in values if _n != bn]
                    new_values.append((value_type, bn, value, 0))
                    return serial, new_values

                def set_xsettings_int(name, value):
                    if value < 0:  # not set, return v unchanged
                        return v
                    return set_xsettings_value(name, XSettingsType.Integer, value)

                if dpi > 0:
                    v = set_xsettings_int("Xft/DPI", dpi * 1024)
                if double_click_time > 0:
                    v = set_xsettings_int("Net/DoubleClickTime", double_click_time)
                if antialias:
                    ad = typedict(antialias)
                    v = set_xsettings_int("Xft/Antialias", ad.intget("enabled", -1))
                    v = set_xsettings_int("Xft/Hinting", ad.intget("hinting", -1))
                    orientation = ad.strget("orientation", "none").lower()
                    v = set_xsettings_value("Xft/RGBA", XSettingsType.String, orientation)
                    v = set_xsettings_value("Xft/HintStyle", XSettingsType.String, _get_antialias_hintstyle(ad))
                if double_click_distance != (-1, -1):
                    # some platforms give us a value for each axis,
                    # but X11 only has one, so take the average
                    try:
                        x, y = double_click_distance
                        if x > 0 and y > 0:
                            d = round((x + y) / 2)
                            d = max(1, min(128, d))  # sanitize it a bit
                            v = set_xsettings_int("Net/DoubleClickDistance", d)
                    except Exception as e:
                        log.warn("error setting double click distance from %s: %s", double_click_distance, e)

            if k not in old_settings or v != old_settings[k]:
                if k == "xsettings-blob":
                    self.set_xsettings(v)
                elif k == "resource-manager":
                    p = "RESOURCE_MANAGER"
                    log(f"server_settings: setting {p} to {v}")
                    root_prop_set(p, "latin1", strtobytes(v).decode("latin1"))
                else:
                    log.warn(f"Warning: unexpected setting {k}")
