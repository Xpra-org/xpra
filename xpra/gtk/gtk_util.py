# This file is part of Xpra.
# Copyright (C) 2011-2023 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os.path
import cairo
import gi
from typing import Any
from collections.abc import Callable

from xpra.gtk.versions import get_gtk_version_info
from xpra.gtk.widget import ignorewarnings
from xpra.util.str_fn import print_nested_dict
from xpra.util.env import envint, envbool
from xpra.os_util import WIN32, OSX, POSIX, is_X11, first_time
from xpra.log import Logger

gi.require_version("Gdk", "3.0")  # @UndefinedVariable
gi.require_version("Gtk", "3.0")  # @UndefinedVariable
gi.require_version("Pango", "1.0")  # @UndefinedVariable
gi.require_version("GdkPixbuf", "2.0")  # @UndefinedVariable
from gi.repository import GObject, Gtk, Gdk     #@UnresolvedImport

log = Logger("gtk", "util")
screenlog = Logger("gtk", "screen")
alphalog = Logger("gtk", "alpha")

SHOW_ALL_VISUALS = False
#try to get workarea from GTK:
GTK_WORKAREA = envbool("XPRA_GTK_WORKAREA", True)


def GDKWindow(*args, **kwargs) -> Gdk.Window:
    return new_GDKWindow(Gdk.Window, *args, **kwargs)

def new_GDKWindow(gdk_window_class,
                  parent=None, width=1, height=1, window_type=Gdk.WindowType.TOPLEVEL,
                  event_mask=0, wclass=Gdk.WindowWindowClass.INPUT_OUTPUT, title=None,
                  x=None, y=None, override_redirect=False, visual=None) -> Gdk.Window:
    attributes_mask = 0
    attributes = Gdk.WindowAttr()
    if x is not None:
        attributes.x = x
        attributes_mask |= Gdk.WindowAttributesType.X
    if y is not None:
        attributes.y = y
        attributes_mask |= Gdk.WindowAttributesType.Y
    #attributes.type_hint = Gdk.WindowTypeHint.NORMAL
    #attributes_mask |= Gdk.WindowAttributesType.TYPE_HINT
    attributes.width = width
    attributes.height = height
    attributes.window_type = window_type
    if title:
        attributes.title = title
        attributes_mask |= Gdk.WindowAttributesType.TITLE
    if visual:
        attributes.visual = visual
        attributes_mask |= Gdk.WindowAttributesType.VISUAL
    #OR:
    attributes.override_redirect = override_redirect
    attributes_mask |= Gdk.WindowAttributesType.NOREDIR
    #events:
    attributes.event_mask = event_mask
    #wclass:
    attributes.wclass = wclass
    mask = Gdk.WindowAttributesType(attributes_mask)
    return gdk_window_class(parent, attributes, mask)

def set_visual(window, alpha : bool=True) -> Gdk.Visual | None:
    screen = window.get_screen()
    if alpha:
        visual = screen.get_rgba_visual()
    else:
        visual = screen.get_system_visual()
    alphalog("set_visual(%s, %s) screen=%s, visual=%s", window, alpha, screen, visual)
    #we can't do alpha on win32 with plain GTK,
    #(though we handle it in the opengl backend)
    l : Callable = alphalog.warn
    if WIN32 or not first_time("no-rgba"):
        l = alphalog.debug
    if alpha and visual is None or (not WIN32 and not screen.is_composited()):
        l("Warning: cannot handle window transparency")
        if visual is None:
            l(" no RGBA visual")
        else:
            assert not screen.is_composited()
            l(" screen is not composited")
        return None
    alphalog("set_visual(%s, %s) using visual %s", window, alpha, visual)
    if visual:
        window.set_visual(visual)
    return visual


def color_parse(*args) -> Gdk.Color | None:
    v = Gdk.RGBA()
    ok = v.parse(*args)
    if ok:
        return v.to_color()  # pylint: disable=no-member
    ok, v = Gdk.Color.parse(*args)
    if ok:
        return v
    return None

def get_default_root_window() -> Gdk.Window | None:
    screen = Gdk.Screen.get_default()
    if screen is None:
        return None
    return screen.get_root_window()

def get_root_size(default:None|tuple[int,int]=(1920, 1024)) -> tuple[int,int] | None:
    if OSX:
        #the easy way:
        root = get_default_root_window()
        if not root:
            return default
        w, h = root.get_geometry()[2:4]
    else:
        #GTK3 on win32 triggers this warning:
        #"GetClientRect failed: Invalid window handle."
        #if we try to use the root window,
        #and on Linux with Wayland, we get bogus values...
        screen = Gdk.Screen.get_default()
        if screen is None:
            return default
        w = ignorewarnings(screen.get_width)
        h = ignorewarnings(screen.get_height)
    if w<=0 or h<=0 or w>32768 or h>32768:
        if first_time("Gtk root window dimensions"):
            log.warn(f"Warning: Gdk returned invalid root window dimensions: {w}x{h}")
            w, h = default
            log.warn(f" using {w}x{h} instead")
            if WIN32:
                log.warn(" no access to the display?")
    return w, h

def get_default_cursor() -> Gdk.Cursor:
    display = Gdk.Display.get_default()
    return Gdk.Cursor.new_from_name(display, "default")


GRAB_STATUS_STRING = {
    Gdk.GrabStatus.SUCCESS          : "SUCCESS",
    Gdk.GrabStatus.ALREADY_GRABBED  : "ALREADY_GRABBED",
    Gdk.GrabStatus.INVALID_TIME     : "INVALID_TIME",
    Gdk.GrabStatus.NOT_VIEWABLE     : "NOT_VIEWABLE",
    Gdk.GrabStatus.FROZEN           : "FROZEN",
    }

VISUAL_NAMES = {
    Gdk.VisualType.STATIC_GRAY      : "STATIC_GRAY",
    Gdk.VisualType.GRAYSCALE        : "GRAYSCALE",
    Gdk.VisualType.STATIC_COLOR     : "STATIC_COLOR",
    Gdk.VisualType.PSEUDO_COLOR     : "PSEUDO_COLOR",
    Gdk.VisualType.TRUE_COLOR       : "TRUE_COLOR",
    Gdk.VisualType.DIRECT_COLOR     : "DIRECT_COLOR",
    }

BYTE_ORDER_NAMES = {
                Gdk.ByteOrder.LSB_FIRST   : "LSB",
                Gdk.ByteOrder.MSB_FIRST   : "MSB",
                }


def get_screens_info() -> dict[int,dict]:
    display = Gdk.Display.get_default()
    info : dict[int,dict] = {}
    assert display.get_n_screens()==1, "GTK3: The number of screens is always 1"
    screen = display.get_screen(0)
    info[0] = get_screen_info(display, screen)
    return info

def get_screen_sizes(xscale:float=1, yscale:float=1):
    from xpra.platform.gui import get_workarea, get_workareas
    def xs(v):
        return round(v/xscale)
    def ys(v):
        return round(v/yscale)
    def swork(*workarea):
        return xs(workarea[0]), ys(workarea[1]), xs(workarea[2]), ys(workarea[3])
    display = Gdk.Display.get_default()
    if not display:
        return ()
    MIN_DPI = envint("XPRA_MIN_DPI", 10)
    MAX_DPI = envint("XPRA_MIN_DPI", 500)
    def dpi(size_pixels, size_mm):
        if size_mm==0:
            return 0
        return round(size_pixels * 254 / size_mm / 10)
    #GTK 3.22 onwards always returns just a single screen,
    #potentially with multiple monitors
    n_monitors = display.get_n_monitors()
    workareas = get_workareas()
    if workareas and len(workareas)!=n_monitors:
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
        def vmwx(v):
            return v<geom.x or v>geom.x+geom.width
        def vmwy(v):
            return v<geom.y or v>geom.y+geom.height
        def valid_workarea(work_x, work_y, work_width, work_height):
            if vmwx(work_x) or vmwx(work_x+work_width) or vmwy(work_y) or vmwy(work_y+work_height):
                log("discarding invalid workarea: %s", (work_x, work_y, work_width, work_height))
                return []
            return list(swork(work_x, work_y, work_width, work_height))
        if GTK_WORKAREA and hasattr(monitor, "get_workarea"):
            rect = monitor.get_workarea()
            monitor_info += valid_workarea(rect.x, rect.y, rect.width, rect.height)
        elif workareas:
            monitor_info += valid_workarea(*workareas[j])
        monitors.append(tuple(monitor_info))
    screen = display.get_default_screen()
    sw, sh = screen.get_width(), screen.get_height()
    work_x, work_y, work_width, work_height = swork(0, 0, sw, sh)
    workarea = get_workarea()   #pylint: disable=assignment-from-none
    screenlog(" workarea=%s", workarea)
    if workarea:
        work_x, work_y, work_width, work_height = swork(*workarea)  #pylint: disable=not-an-iterable
        def vwx(v):
            return v<0 or v>sw
        def vwy(v):
            return v<0 or v>sh
        if vwx(work_x) or vwx(work_x+work_width) or vwy(work_y) or vwy(work_y+work_height):
            screenlog(" discarding invalid workarea values: %s", workarea)
            work_x, work_y, work_width, work_height = swork(0, 0, sw, sh)
    wmm = ignorewarnings(screen.get_width_mm)
    hmm = ignorewarnings(screen.get_height_mm)
    xdpi = dpi(sw, wmm)
    ydpi = dpi(sh, hmm)
    if xdpi<MIN_DPI or xdpi>MAX_DPI or ydpi<MIN_DPI or ydpi>MAX_DPI:
        log(f"ignoring invalid DPI {xdpi},{ydpi} from screen size {wmm}x{hmm}mm")
        if os.environ.get("WAYLAND_DISPLAY"):
            log(" (wayland display?)")
        if n_monitors>0:
            wmm = 0
            for mi in range(n_monitors):
                monitor = display.get_monitor(mi)
                log(" monitor %i: %s, model=%s, manufacturer=%s",
                    mi, monitor, monitor.get_model(), monitor.get_manufacturer())
                wmm += monitor.get_width_mm()
                hmm += monitor.get_height_mm()
            wmm /= n_monitors
            hmm /= n_monitors
            xdpi = dpi(sw, wmm)
            ydpi = dpi(sh, hmm)
        if xdpi<MIN_DPI or xdpi>MAX_DPI or ydpi<MIN_DPI or ydpi>MAX_DPI:
            #still invalid, generate one from DPI=96
            wmm = round(sw*25.4/96)
            hmm = round(sh*25.4/96)
        log(" using %ix%i mm", wmm, hmm)
    screen0 = (ignorewarnings(screen.make_display_name), xs(sw), ys(sh),
               wmm, hmm,
               monitors,
               work_x, work_y, work_width, work_height)
    screenlog(" screen: %s", screen0)
    return [screen0]

def get_screen_info(display, screen) -> dict[str,Any]:
    info = {}
    if not WIN32:
        try:
            w = screen.get_root_window()
            if w:
                info["root"] = w.get_geometry()
        except Exception:
            pass
    info["name"] = screen.make_display_name()
    for x in ("width", "height", "width_mm", "height_mm", "resolution", "primary_monitor"):
        fn = getattr(screen, "get_"+x)
        try:
            info[x] = int(fn())
        except Exception:
            pass
    info["monitors"] = display.get_n_monitors()
    m_info = info.setdefault("monitor", {})
    for i in range(screen.get_n_monitors()):
        m_info[i] = get_screen_monitor_info(screen, i)
    fo = screen.get_font_options()
    #win32 and osx return nothing here...
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
    #Gtk.settings
    def get_setting(key, gtype):
        v = GObject.Value()
        v.init(gtype)
        if screen.get_setting(key, v):
            return v.get_value()
        return None
    sinfo = info.setdefault("settings", {})
    for x, gtype in {
        #NET:
        "enable-event-sounds"   : GObject.TYPE_INT,
        "icon-theme-name"       : GObject.TYPE_STRING,
        "sound-theme-name"      : GObject.TYPE_STRING,
        "theme-name"            : GObject.TYPE_STRING,
        #Xft:
        "xft-antialias" : GObject.TYPE_INT,
        "xft-dpi"       : GObject.TYPE_INT,
        "xft-hinting"   : GObject.TYPE_INT,
        "xft-hintstyle" : GObject.TYPE_STRING,
        "xft-rgba"      : GObject.TYPE_STRING,
        }.items():
        try:
            v = get_setting("gtk-"+x, gtype)
        except Exception:
            log("failed to query screen '%s'", x, exc_info=True)
            continue
        if v is None:
            v = ""
        if x.startswith("xft-"):
            x = x[4:]
        sinfo[x] = v
    return info

FONT_CONV : dict[str,dict[Any,Any]] = {
    "antialias" : {
        cairo.ANTIALIAS_DEFAULT     : "default",
        cairo.ANTIALIAS_NONE        : "none",
        cairo.ANTIALIAS_GRAY        : "gray",
        cairo.ANTIALIAS_SUBPIXEL    : "subpixel",
        },
    "hint_metrics" : {
        cairo.HINT_METRICS_DEFAULT  : "default",
        cairo.HINT_METRICS_OFF      : "off",
        cairo.HINT_METRICS_ON       : "on",
        },
    "hint_style" : {
        cairo.HINT_STYLE_DEFAULT    : "default",
        cairo.HINT_STYLE_NONE       : "none",
        cairo.HINT_STYLE_SLIGHT     : "slight",
        cairo.HINT_STYLE_MEDIUM     : "medium",
        cairo.HINT_STYLE_FULL       : "full",
        },
    "subpixel_order": {
        cairo.SUBPIXEL_ORDER_DEFAULT    : "default",
        cairo.SUBPIXEL_ORDER_RGB        : "RGB",
        cairo.SUBPIXEL_ORDER_BGR        : "BGR",
        cairo.SUBPIXEL_ORDER_VRGB       : "VRGB",
        cairo.SUBPIXEL_ORDER_VBGR       : "VBGR",
        }
    }

def get_font_info(font_options) -> dict[str,Any]:
    #pylint: disable=no-member
    font_info : dict[str,Any] = {}
    for x,vdict in FONT_CONV.items():
        fn = getattr(font_options, "get_"+x)
        val = fn()
        font_info[x] = vdict.get(val, val)
    return font_info

VINFO_CONV : dict[str,dict[Any,str]] = {
        "bits_per_rgb"          : {},
        "byte_order"            : BYTE_ORDER_NAMES,
        "colormap_size"         : {},
        "depth"                 : {},
        "red_pixel_details"     : {},
        "green_pixel_details"   : {},
        "blue_pixel_details"    : {},
        "visual_type"           : VISUAL_NAMES,
        }

def get_visual_info(v) -> dict[str,Any]:
    if not v:
        return {}
    vinfo : dict[str,Any] = {}
    for x, vdict in VINFO_CONV.items():
        val = None
        try:
            #ugly workaround for "visual_type" -> "type" for GTK2...
            val = getattr(v, x.replace("visual_", ""))
        except AttributeError:
            try:
                fn = getattr(v, "get_"+x)
            except AttributeError:
                pass
            else:
                val = fn()
        if val is not None:
            vinfo[x] = vdict.get(val, val)
    return vinfo

def get_screen_monitor_info(screen, i) -> dict[str,Any]:
    info : dict[str,Any] = {}
    geom = screen.get_monitor_geometry(i)
    for x in ("x", "y", "width", "height"):
        info[x] = getattr(geom, x)
    if hasattr(screen, "get_monitor_plug_name"):
        info["plug_name"] = screen.get_monitor_plug_name(i) or ""
    for x in ("scale_factor", "width_mm", "height_mm", "refresh_rate"):
        fn = getattr(screen, "get_monitor_"+x, None) or getattr(screen, "get_"+x, None)
        if fn:
            info[x] = int(fn(i))
    rectangle = screen.get_monitor_workarea(i)
    workarea_info = info.setdefault("workarea", {})
    for x in ("x", "y", "width", "height"):
        workarea_info[x] = getattr(rectangle, x)
    return info

def get_monitors_info(xscale:float=1, yscale:float=1) -> dict[int,Any]:
    display = Gdk.Display.get_default()
    info : dict[int,Any] = {}
    n = display.get_n_monitors()
    for i in range(n):
        minfo = info.setdefault(i, {})
        monitor = display.get_monitor(i)
        minfo["primary"] = monitor.is_primary()
        for attr in (
            "geometry", "refresh-rate", "scale-factor",
            "width-mm", "height-mm",
            "manufacturer", "model",
            "subpixel-layout",  "workarea",
            ):
            getter = getattr(monitor, "get_%s" % attr.replace("-", "_"), None)
            if getter:
                value = getter()
                if value is None:
                    continue
                if isinstance(value, Gdk.Rectangle):
                    value = (round(xscale*value.x), round(yscale*value.y), round(xscale*value.width), round(yscale*value.height))
                elif attr=="width-mm":
                    value = round(xscale*value)
                elif attr=="height-mm":
                    value = round(yscale*value)
                elif attr=="subpixel-layout":
                    value = {
                        Gdk.SubpixelLayout.UNKNOWN          : "unknown",
                        Gdk.SubpixelLayout.NONE             : "none",
                        Gdk.SubpixelLayout.HORIZONTAL_RGB   : "horizontal-rgb",
                        Gdk.SubpixelLayout.HORIZONTAL_BGR   : "horizontal-bgr",
                        Gdk.SubpixelLayout.VERTICAL_RGB     : "vertical-rgb",
                        Gdk.SubpixelLayout.VERTICAL_BGR     : "vertical-bgr",
                        }.get(value, "unknown")
                if isinstance(value, str):
                    value = value.strip()
                minfo[attr] = value
    return info

def get_display_info(xscale=1, yscale=1) -> dict[str,Any]:
    display = Gdk.Display.get_default()
    def xy(v):
        return round(xscale*v[0]), round(yscale*v[1])
    def avg(v):
        return round((xscale*v+yscale*v)/2)
    root_size = get_root_size()
    info : dict[str, Any] = {
            "root-size"             : xy(root_size),
            "screens"               : display.get_n_screens(),
            "name"                  : display.get_name(),
            "pointer"               : xy(display.get_pointer()[-3:-1]),
            "devices"               : len(display.list_devices()),
            "default_cursor_size"   : avg(display.get_default_cursor_size()),
            "maximal_cursor_size"   : xy(display.get_maximal_cursor_size()),
            "pointer_is_grabbed"    : display.pointer_is_grabbed(),
            }
    if not WIN32:
        rw = get_default_root_window()
        if rw:
            info["root"] = rw.get_geometry()
    sinfo = info.setdefault("supports", {})
    for x in ("composite", "cursor_alpha", "cursor_color", "selection_notification", "clipboard_persistence", "shapes"):
        f = "supports_"+x
        if hasattr(display, f):
            fn = getattr(display, f)
            sinfo[x]  = fn()
    info["screens"] = get_screens_info()
    info["monitors"] = get_monitors_info(xscale, yscale)
    dm = display.get_device_manager()
    for dt, name in {
        Gdk.DeviceType.MASTER  : "master",
        Gdk.DeviceType.SLAVE   : "slave",
        Gdk.DeviceType.FLOATING: "floating",
        }.items():
        dinfo = info.setdefault("device", {})
        dtinfo = dinfo.setdefault(name, {})
        devices = dm.list_devices(dt)
        for i, d in enumerate(devices):
            dtinfo[i] = d.get_name()
    return info


def add_close_accel(window, callback):
    accel_groups = []
    def wa(s, cb):
        accel_groups.append(add_window_accel(window, s, cb))
    wa('<control>F4', callback)
    wa('<Alt>F4', callback)
    wa('Escape', callback)
    return accel_groups

def add_window_accel(window, accel, callback) -> Gtk.AccelGroup:
    def connect(ag, *args):
        ag.connect(*args)
    accel_group = Gtk.AccelGroup()
    key, mod = Gtk.accelerator_parse(accel)
    connect(accel_group, key, mod, Gtk.AccelFlags.LOCKED, callback)
    window.add_accel_group(accel_group)
    return accel_group


dsinit : bool = False
def init_display_source() -> None:
    """
    On X11, we want to be able to access the bindings,
    so we need to get the X11 display from GDK.
    """
    global dsinit
    dsinit = True
    if is_X11():
        try:
            from xpra.x11.gtk3.gdk_display_source import init_gdk_display_source
            init_gdk_display_source()
        except ImportError:     # pragma: no cover
            from xpra.log import Logger
            log = Logger("gtk", "client")
            log("init_gdk_display_source()", exc_info=True)
            log.warn("Warning: the Gtk-3.0 X11 bindings are missing")
            log.warn(" some features may be degraded or unavailable")
            log.warn(" ie: keyboard mapping, focus, etc")

def ds_inited() -> bool:
    return dsinit


def main():
    from xpra.platform import program_context
    from xpra.log import enable_color
    with program_context("GTK-Version-Info", "GTK Version Info"):
        enable_color()
        print("%s" % get_gtk_version_info())
        if POSIX and not OSX:
            from xpra.x11.bindings.posix_display_source import init_posix_display_source    #@UnresolvedImport
            init_posix_display_source()
        import warnings
        warnings.simplefilter("ignore")
        print(get_screen_sizes()[0])
        print_nested_dict(get_display_info())


if __name__ == "__main__":
    main()