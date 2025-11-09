#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2015 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import sys
from typing import Any
from collections.abc import Callable
import cairo

from xpra.common import noop
from xpra.gtk.util import get_root_size, get_default_root_window
from xpra.os_util import WIN32, gi_import
from xpra.util.env import envint, envbool, IgnoreWarningsContext
from xpra.log import Logger, consume_verbose_argv

Gdk = gi_import("Gdk")
GObject = gi_import("GObject")

log = Logger("gtk", "util")
screenlog = Logger("gtk", "screen")

SHOW_ALL_VISUALS = False
GTK_WORKAREA = envbool("XPRA_GTK_WORKAREA", True)


def get_screen_info(display, screen) -> dict[str, Any]:
    info = {}
    if not WIN32:
        try:
            w = screen.get_root_window()
            if w:
                info["root"] = w.get_geometry()
        except Exception:
            pass
    with IgnoreWarningsContext():
        info["name"] = screen.make_display_name()
    with IgnoreWarningsContext():
        for x in ("width", "height", "width_mm", "height_mm", "resolution", "primary_monitor"):
            fn = getattr(screen, "get_" + x)
            try:
                info[x] = int(fn())
            except Exception:
                pass
    info["monitors"] = display.get_n_monitors()
    m_info = info.setdefault("monitor", {})
    for i in range(display.get_n_monitors()):
        monitor = display.get_monitor(i)
        m_info[i] = get_monitor_info(monitor)
    fo = screen.get_font_options()
    # win32 and osx return nothing here...
    if fo:
        fontoptions = info.setdefault("fontoptions", {})
        fontoptions.update(get_font_info(fo))
    vinfo = info.setdefault("visual", {})

    def visual(name, v):
        i = get_visual_info(v)
        if i:
            vinfo[name] = i

    visual("rgba", screen.get_rgba_visual())
    visual("system_visual", screen.get_system_visual())
    if SHOW_ALL_VISUALS:
        for i, v in enumerate(screen.list_visuals()):
            visual(i, v)

    # Gtk.settings
    def get_setting(key: str, gtype):
        v = GObject.Value()
        v.init(gtype)
        if screen.get_setting(key, v):
            return v.get_value()
        return None

    sinfo = info.setdefault("settings", {})
    for x, gtype in {
        # NET:
        "enable-event-sounds": GObject.TYPE_INT,
        "icon-theme-name": GObject.TYPE_STRING,
        "sound-theme-name": GObject.TYPE_STRING,
        "theme-name": GObject.TYPE_STRING,
        # Xft:
        "xft-antialias": GObject.TYPE_INT,
        "xft-dpi": GObject.TYPE_INT,
        "xft-hinting": GObject.TYPE_INT,
        "xft-hintstyle": GObject.TYPE_STRING,
        "xft-rgba": GObject.TYPE_STRING,
    }.items():
        try:
            v = get_setting("gtk-" + x, gtype)
        except Exception:
            screenlog("failed to query screen '%s'", x, exc_info=True)
            continue
        if v is None:
            v = ""
        if x.startswith("xft-"):
            x = x[4:]
        sinfo[x] = v
    return info


FONT_CONV: dict[str, dict[Any, Any]] = {
    "antialias": {
        cairo.ANTIALIAS_DEFAULT: "default",
        cairo.ANTIALIAS_NONE: "none",
        cairo.ANTIALIAS_GRAY: "gray",
        cairo.ANTIALIAS_SUBPIXEL: "subpixel",
    },
    "hint_metrics": {
        cairo.HINT_METRICS_DEFAULT: "default",
        cairo.HINT_METRICS_OFF: "off",
        cairo.HINT_METRICS_ON: "on",
    },
    "hint_style": {
        cairo.HINT_STYLE_DEFAULT: "default",
        cairo.HINT_STYLE_NONE: "none",
        cairo.HINT_STYLE_SLIGHT: "slight",
        cairo.HINT_STYLE_MEDIUM: "medium",
        cairo.HINT_STYLE_FULL: "full",
    },
    "subpixel_order": {
        cairo.SUBPIXEL_ORDER_DEFAULT: "default",
        cairo.SUBPIXEL_ORDER_RGB: "RGB",
        cairo.SUBPIXEL_ORDER_BGR: "BGR",
        cairo.SUBPIXEL_ORDER_VRGB: "VRGB",
        cairo.SUBPIXEL_ORDER_VBGR: "VBGR",
    }
}


def get_font_info(font_options: cairo.FontOptions) -> dict[str, Any]:
    # pylint: disable=no-member
    font_info: dict[str, Any] = {}
    for x, vdict in FONT_CONV.items():
        fn = getattr(font_options, "get_" + x)
        val = fn()
        font_info[x] = vdict.get(val, val)
    return font_info


VISUAL_NAMES: dict[Gdk.VisualType, str] = {
    Gdk.VisualType.STATIC_GRAY: "STATIC_GRAY",
    Gdk.VisualType.GRAYSCALE: "GRAYSCALE",
    Gdk.VisualType.STATIC_COLOR: "STATIC_COLOR",
    Gdk.VisualType.PSEUDO_COLOR: "PSEUDO_COLOR",
    Gdk.VisualType.TRUE_COLOR: "TRUE_COLOR",
    Gdk.VisualType.DIRECT_COLOR: "DIRECT_COLOR",
}
BYTE_ORDER_NAMES: dict[Gdk.ByteOrder, str] = {
    Gdk.ByteOrder.LSB_FIRST: "LSB",
    Gdk.ByteOrder.MSB_FIRST: "MSB",
}
SUBPIXEL_LAYOUT: dict[Gdk.SubpixelLayout, str] = {
    Gdk.SubpixelLayout.UNKNOWN: "unknown",
    Gdk.SubpixelLayout.NONE: "none",
    Gdk.SubpixelLayout.HORIZONTAL_RGB: "horizontal-rgb",
    Gdk.SubpixelLayout.HORIZONTAL_BGR: "horizontal-bgr",
    Gdk.SubpixelLayout.VERTICAL_RGB: "vertical-rgb",
    Gdk.SubpixelLayout.VERTICAL_BGR: "vertical-bgr",
}
VINFO_CONV: dict[str, dict[Any, str]] = {
    "bits_per_rgb": {},
    "byte_order": BYTE_ORDER_NAMES,
    "colormap_size": {},
    "depth": {},
    "red_pixel_details": {},
    "green_pixel_details": {},
    "blue_pixel_details": {},
    "visual_type": VISUAL_NAMES,
}


def get_visual_info(v) -> dict[str, Any]:
    if not v:
        return {}
    vinfo: dict[str, Any] = {}
    for x, vdict in VINFO_CONV.items():
        try:
            fn = getattr(v, "get_" + x)
        except AttributeError:
            pass
        else:
            with IgnoreWarningsContext():
                val = fn()
            if val is not None:
                vinfo[x] = vdict.get(val, val)
    return vinfo


def get_rectangle_info(rect: Gdk.Rectangle) -> dict[str, int]:
    info: dict[str, int] = {}
    for x in ("x", "y", "width", "height"):
        info[x] = getattr(rect, x)
    return info


def get_average_monitor_refresh_rate() -> int:
    rates = {}
    display = Gdk.Display.get_default()
    for m in range(display.get_n_monitors()):
        monitor = display.get_monitor(m)
        log(f"monitor {m} ({monitor.get_model()}) refresh-rate={monitor.get_refresh_rate()}")
        rates[m] = monitor.get_refresh_rate()
    rate = -1
    if rates:
        rate = round(min(rates.values()) / 1000)
    return rate


def get_monitor_info(monitor: Gdk.Monitor) -> dict[str, Any]:
    geom = monitor.get_geometry()
    info: dict[str, Any] = get_rectangle_info(geom)
    for x in ("manufacturer", "model"):
        info[x] = getattr(monitor, f"get_{x}", noop)() or ""
    for x in ("scale_factor", "width_mm", "height_mm", "refresh_rate"):
        if hasattr(monitor, f"get_{x}"):
            fn: Callable = getattr(monitor, f"get_{x}")
            info[x] = int(fn())
    workarea = monitor.get_workarea()
    info["workarea"] = get_rectangle_info(workarea)
    subpixel = monitor.get_subpixel_layout()
    info["subpixel-layout"] = SUBPIXEL_LAYOUT.get(subpixel, "unknown")
    return info


def get_monitors_info(xscale: float = 1.0, yscale: float = 1.0) -> dict[int, Any]:
    display = Gdk.Display.get_default()
    info: dict[int, Any] = {}
    n = display.get_n_monitors()
    for i in range(n):
        minfo = info.setdefault(i, {})
        monitor = display.get_monitor(i)
        minfo["primary"] = monitor.is_primary()
        for attr in (
                "geometry", "refresh-rate", "scale-factor",
                "width-mm", "height-mm",
                "manufacturer", "model",
                "subpixel-layout", "workarea",
        ):
            getter = getattr(monitor, "get_%s" % attr.replace("-", "_"), None)
            if getter:
                value = getter()
                if value is None:
                    continue
                if isinstance(value, Gdk.Rectangle):
                    value = (
                        round(value.x / xscale),
                        round(value.y / yscale),
                        round(value.width / xscale),
                        round(value.height / yscale),
                    )
                elif attr == "width-mm":
                    value = round(value / xscale)
                elif attr == "height-mm":
                    value = round(value / yscale)
                elif attr == "subpixel-layout":
                    value = {
                        Gdk.SubpixelLayout.UNKNOWN: "unknown",
                        Gdk.SubpixelLayout.NONE: "none",
                        Gdk.SubpixelLayout.HORIZONTAL_RGB: "horizontal-rgb",
                        Gdk.SubpixelLayout.HORIZONTAL_BGR: "horizontal-bgr",
                        Gdk.SubpixelLayout.VERTICAL_RGB: "vertical-rgb",
                        Gdk.SubpixelLayout.VERTICAL_BGR: "vertical-bgr",
                    }.get(value, "unknown")
                if isinstance(value, str):
                    value = value.strip()
                minfo[attr] = value
    return info


def get_display_info(xscale=1, yscale=1) -> dict[str, Any]:
    display = Gdk.Display.get_default()

    def xy(v) -> tuple[int, int]:
        return round(xscale * v[0]), round(yscale * v[1])

    def avg(v) -> int:
        return round((xscale * v + yscale * v) / 2)

    root_size = get_root_size()
    with IgnoreWarningsContext():
        info: dict[str, Any] = {
            "root-size": xy(root_size),
            "name": display.get_name(),
            "pointer": xy(display.get_pointer()[-3:-1]),
            "devices": len(display.list_devices()),
            "default_cursor_size": avg(display.get_default_cursor_size()),
            "maximal_cursor_size": xy(display.get_maximal_cursor_size()),
            "pointer_is_grabbed": display.pointer_is_grabbed(),
        }
    if not WIN32:
        rw = get_default_root_window()
        if rw:
            info["root"] = rw.get_geometry()
    sinfo = info.setdefault("supports", {})
    for x in ("composite", "cursor_alpha", "cursor_color", "selection_notification", "clipboard_persistence", "shapes"):
        f = "supports_" + x
        if hasattr(display, f):
            fn = getattr(display, f)
            with IgnoreWarningsContext():
                sinfo[x] = fn()
    info["screens"] = get_screens_info()
    info["monitors"] = get_monitors_info(xscale, yscale)
    with IgnoreWarningsContext():
        dm = display.get_device_manager()
        for dt, name in {
            Gdk.DeviceType.MASTER: "master",
            Gdk.DeviceType.SLAVE: "slave",
            Gdk.DeviceType.FLOATING: "floating",
        }.items():
            dinfo = info.setdefault("device", {})
            dtinfo = dinfo.setdefault(name, {})
            devices = dm.list_devices(dt)
            for i, d in enumerate(devices):
                dtinfo[i] = d.get_name()
    return info


def get_screens_info() -> dict[int, dict]:
    display = Gdk.Display.get_default()
    info: dict[int, dict] = {}
    with IgnoreWarningsContext():
        assert display.get_n_screens() == 1, "GTK3: The number of screens is always 1"
        screen = display.get_screen(0)
    info[0] = get_screen_info(display, screen)
    return info


def get_screen_sizes(xscale: float = 1, yscale: float = 1) -> list[tuple[int, int]]:
    from xpra.platform.gui import get_workarea, get_workareas

    def xs(v) -> int:
        return round(v / xscale)

    def ys(v) -> int:
        return round(v / yscale)

    def swork(*workarea) -> tuple[int, int, int, int]:
        return xs(workarea[0]), ys(workarea[1]), xs(workarea[2]), ys(workarea[3])

    display = Gdk.Display.get_default()
    if not display:
        return []
    MIN_DPI = envint("XPRA_MIN_DPI", 10)
    MAX_DPI = envint("XPRA_MIN_DPI", 500)

    def dpi(size_pixels: int, size_mm: int) -> int:
        if size_mm == 0:
            return 0
        return round(size_pixels * 254 / size_mm / 10)

    # GTK 3.22 onwards always returns just a single screen,
    # potentially with multiple monitors
    n_monitors = display.get_n_monitors()
    workareas = get_workareas()
    if workareas and len(workareas) != n_monitors:
        screenlog(" workareas: %s", workareas)
        screenlog(" number of monitors does not match number of workareas!")
        workareas = []
    monitors = []
    for j in range(n_monitors):
        monitor = display.get_monitor(j)
        geom = monitor.get_geometry()
        manufacturer, model = monitor.get_manufacturer(), monitor.get_model()
        if manufacturer in ("unknown", None):
            manufacturer = ""
        if model in ("unknown", None):
            model = ""
        if manufacturer and model:
            plug_name = "%s %s" % (manufacturer, model)
        elif manufacturer:
            plug_name = manufacturer
        elif model:
            plug_name = model
        else:
            plug_name = "%i" % j
        wmm, hmm = monitor.get_width_mm(), monitor.get_height_mm()
        monitor_info = [plug_name, xs(geom.x), ys(geom.y), xs(geom.width), ys(geom.height), wmm, hmm]
        screenlog(" monitor %s: %s, model=%s, manufacturer=%s",
                  j, type(monitor).__name__, monitor.get_model(), monitor.get_manufacturer())

        def vmwx(v) -> bool:
            return v < geom.x or v > geom.x + geom.width

        def vmwy(v) -> bool:
            return v < geom.y or v > geom.y + geom.height

        def valid_workarea(work_x, work_y, work_width, work_height) -> list[int]:
            if vmwx(work_x) or vmwx(work_x + work_width) or vmwy(work_y) or vmwy(work_y + work_height):
                screenlog("discarding invalid workarea: %s", (work_x, work_y, work_width, work_height))
                return []
            return list(swork(work_x, work_y, work_width, work_height))

        if GTK_WORKAREA and hasattr(monitor, "get_workarea"):
            rect = monitor.get_workarea()
            monitor_info += valid_workarea(rect.x, rect.y, rect.width, rect.height)
        elif workareas:
            monitor_info += valid_workarea(*workareas[j])
        monitors.append(tuple(monitor_info))
    screen = display.get_default_screen()
    with IgnoreWarningsContext():
        sw, sh = screen.get_width(), screen.get_height()
    work_x, work_y, work_width, work_height = swork(0, 0, sw, sh)
    workarea = get_workarea()  # pylint: disable=assignment-from-none
    screenlog(" workarea=%s", workarea)
    if workarea:
        work_x, work_y, work_width, work_height = swork(*workarea)  # pylint: disable=not-an-iterable

        def vwx(v) -> bool:
            return v < 0 or v > sw

        def vwy(v) -> bool:
            return v < 0 or v > sh

        if vwx(work_x) or vwx(work_x + work_width) or vwy(work_y) or vwy(work_y + work_height):
            screenlog(" discarding invalid workarea values: %s", workarea)
            work_x, work_y, work_width, work_height = swork(0, 0, sw, sh)
    with IgnoreWarningsContext():
        wmm = screen.get_width_mm()
        hmm = screen.get_height_mm()
    xdpi = dpi(sw, wmm)
    ydpi = dpi(sh, hmm)
    if xdpi < MIN_DPI or xdpi > MAX_DPI or ydpi < MIN_DPI or ydpi > MAX_DPI:
        screenlog(f"ignoring invalid DPI {xdpi},{ydpi} from screen size {wmm}x{hmm}mm")
        if os.environ.get("WAYLAND_DISPLAY", ""):
            screenlog(" (wayland display?)")
        if n_monitors > 0:
            wmm = 0
            for mi in range(n_monitors):
                monitor = display.get_monitor(mi)
                screenlog(" monitor %i: %s, model=%s, manufacturer=%s",
                          mi, monitor, monitor.get_model(), monitor.get_manufacturer())
                wmm += monitor.get_width_mm()
                hmm += monitor.get_height_mm()
            wmm /= n_monitors
            hmm /= n_monitors
            xdpi = dpi(sw, wmm)
            ydpi = dpi(sh, hmm)
        if xdpi < MIN_DPI or xdpi > MAX_DPI or ydpi < MIN_DPI or ydpi > MAX_DPI:
            # still invalid, generate one from DPI=96
            wmm = round(sw * 25.4 / 96)
            hmm = round(sh * 25.4 / 96)
        screenlog(" using %ix%i mm", wmm, hmm)
    with IgnoreWarningsContext():
        screen0 = (screen.make_display_name(), xs(sw), ys(sh),
                   wmm, hmm,
                   monitors,
                   work_x, work_y, work_width, work_height)
    screenlog(" screen: %s", screen0)
    return [screen0]


def main() -> int:
    # pylint: disable=import-outside-toplevel
    from xpra.util.str_fn import pver
    from xpra.util.str_fn import print_nested_dict

    def print_version_dict(d: dict, vformat=pver) -> None:
        for k in sorted(d.keys()):
            v = d[k]
            print("* %-48s : %r" % (str(k).replace(".version", "").ljust(12), vformat(v)))

    from xpra.platform import program_context
    with program_context("GTK-Version-Info", "GTK Version Info"):
        from xpra.platform.gui import init as gui_init, ready
        gui_init()
        ready()
        if consume_verbose_argv(sys.argv, "gtk"):
            global SHOW_ALL_VISUALS
            SHOW_ALL_VISUALS = True
        print("GTK Version:")
        from xpra.gtk import versions
        print_version_dict(versions.get_gtk_version_info())
        print("Display:")
        print_nested_dict(get_display_info(), vformat=str)
    return 0


if __name__ == "__main__":
    sys.exit(main())
