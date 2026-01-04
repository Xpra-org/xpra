# This file is part of Xpra.
# Copyright (C) 2018 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
from typing import Any

from xpra.net.common import Packet
from xpra.util.env import envbool
from xpra.util.str_fn import bytestostr, strtobytes
from xpra.util.parsing import str_to_bool
from xpra.server.subsystem.stub import StubServerMixin
from xpra.x11.error import xsync
from xpra.x11.subsystem.xsettings_prop import XSettingsType
from xpra.server import features
from xpra.util.objects import typedict
from xpra.log import Logger

log = Logger("x11", "server", "xsettings")

BLOCKLISTED_XSETTINGS: list[str] = os.environ.get(
    "XPRA_BLOCKLISTED_XSETTINGS",
    "Gdk/WindowScalingFactor,Gtk/SessionBusId,Gtk/IMModule"
).split(",")
SCALED_FONT_ANTIALIAS = envbool("XPRA_SCALED_FONT_ANTIALIAS", False)


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


class XSettingsServer(StubServerMixin):

    def __init__(self):
        StubServerMixin.__init__(self)
        self._default_xsettings: tuple[int, list[tuple]] = (0, [])
        self._settings: dict[str, Any] = {}
        self._xsettings_enabled = False
        self._xsettings_manager = None

    def init(self, opts) -> None:
        # the server class sets the default value for 'xsettings_enabled'
        # it is overridden in the seamless server (enabled by default),
        # and we let the options have the final say here:
        self._xsettings_enabled = str_to_bool(opts.xsettings, self._xsettings_enabled)
        log("xsettings_enabled(%s)=%s", opts.xsettings, self._xsettings_enabled)

    def setup(self) -> None:
        if self._xsettings_enabled:
            from xpra.x11.subsystem.xsettings_manager import XSettingsHelper
            self._default_xsettings = XSettingsHelper().get_settings()
            log("_default_xsettings=%s", self._default_xsettings)
            self.init_all_server_settings()

    def last_client_exited(self) -> None:
        self.reset_settings()

    def get_caps(self, _source) -> dict[str, Any]:
        return {}

    def get_ui_info(self, proto, **kwargs) -> dict[str, Any]:
        return {}

    def init_packet_handlers(self) -> None:
        self.add_packets("server-settings", main_thread=True)

    def _process_server_settings(self, _proto, packet: Packet) -> None:
        settings = packet.get_dict(1)
        log("process_server_settings: %s", settings)
        self.update_server_settings(settings)

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
                from xpra.x11.subsystem.xsettings_manager import XSettingsManager
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
            dc_time = getattr(self, "double_click_time", 0)
            dc_distance = getattr(self, "double_click_distance", (-1, -1))
            have_override = dc_time > 0 or dc_distance != (-1, -1) or antialias or dpi > 0
            if k == "xsettings-blob" and have_override:
                # start by removing blocklisted options:
                def filter_blocklisted() -> tuple[int, list]:
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
                    from xpra.x11.xroot_props import root_set
                    root_set(p, "latin1", strtobytes(v).decode("latin1"))
                else:
                    log.warn(f"Warning: unexpected setting {k}")
