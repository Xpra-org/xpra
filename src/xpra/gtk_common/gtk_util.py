# -*- coding: utf-8 -*-
# This file is part of Xpra.
# Copyright (C) 2011-2020 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os.path
import cairo

import gi
gi.require_version("Gdk", "3.0")
gi.require_version("Gtk", "3.0")
gi.require_version("Pango", "1.0")
gi.require_version("GdkPixbuf", "2.0")
from gi.repository import GLib, GdkPixbuf, Pango, GObject, Gtk, Gdk     #@UnresolvedImport

from xpra.util import iround, first_time, envint
from xpra.os_util import strtobytes, WIN32, OSX, POSIX
from xpra.log import Logger

log = Logger("gtk", "util")
screenlog = Logger("gtk", "screen")
alphalog = Logger("gtk", "alpha")

SHOW_ALL_VISUALS = False

GTK_VERSION_INFO = {}
def get_gtk_version_info() -> dict:
    #update props given:
    global GTK_VERSION_INFO
    def av(k, v):
        GTK_VERSION_INFO.setdefault(k, {})["version"] = v
    def V(k, module, *fields):
        for field in fields:
            v = getattr(module, field, None)
            if v is not None:
                av(k, v)
                return True
        return False

    if not GTK_VERSION_INFO:
        V("gobject",    GObject,    "pygobject_version")

        #this isn't the actual version, (only shows as "3.0")
        #but still better than nothing:
        import gi
        V("gi",         gi,         "__version__")
        V("gtk",        Gtk,        "_version")
        V("gdk",        Gdk,        "_version")
        V("gobject",    GObject,    "_version")
        V("pixbuf",     GdkPixbuf,     "_version")

        av("pygtk", "n/a")
        V("pixbuf",     GdkPixbuf,     "PIXBUF_VERSION")
        def MAJORMICROMINOR(name, module):
            try:
                v = tuple(getattr(module, x) for x in ("MAJOR_VERSION", "MICRO_VERSION", "MINOR_VERSION"))
                av(name, ".".join(str(x) for x in v))
            except:
                pass
        MAJORMICROMINOR("gtk",  Gtk)
        MAJORMICROMINOR("glib", GLib)

        #from here on, the code is the same for both GTK2 and GTK3, hooray:
        vi = getattr(cairo, "version_info", None)
        if vi:
            av("cairo", vi)
        else:
            vfn = getattr(cairo, "cairo_version_string", None)
            if vfn:
                av("cairo", vfn())
        vfn = getattr(Pango, "version_string")
        if vfn:
            av("pango", vfn())
    return GTK_VERSION_INFO.copy()


def pixbuf_save_to_memory(pixbuf, fmt="png") -> bytes:
    buf = []
    def save_to_memory(data, *_args, **_kwargs):
        buf.append(strtobytes(data))
        return True
    pixbuf.save_to_callbackv(save_to_memory, None, fmt, [], [])
    return b"".join(buf)


def GDKWindow(parent=None, width=1, height=1, window_type=Gdk.WindowType.TOPLEVEL,
              event_mask=0, wclass=Gdk.WindowWindowClass.INPUT_OUTPUT, title=None,
              x=None, y=None, override_redirect=False, visual=None, **kwargs) -> Gdk.Window:
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
    return Gdk.Window(parent, attributes, mask)

def enable_alpha(window) -> bool:
    screen = window.get_screen()
    visual = screen.get_rgba_visual()
    alphalog("enable_alpha(%s) screen=%s, visual=%s", window, screen, visual)
    #we can't do alpha on win32 with plain GTK,
    #(though we handle it in the opengl backend)
    if WIN32:
        l = alphalog
    else:
        l = alphalog.warn
    if visual is None or (not WIN32 and not screen.is_composited()):
        l("Warning: cannot handle window transparency")
        if visual is None:
            l(" no RGBA visual")
        else:
            assert not screen.is_composited()
            l(" screen is not composited")
        return False
    alphalog("enable_alpha(%s) using rgba visual %s", window, visual)
    window.set_visual(visual)
    return True


def get_pixbuf_from_data(rgb_data, has_alpha : bool, w : int, h : int, rowstride : int) -> GdkPixbuf.Pixbuf:
    data = GLib.Bytes(rgb_data)
    return GdkPixbuf.Pixbuf.new_from_bytes(data, GdkPixbuf.Colorspace.RGB,
                                           has_alpha, 8, w, h, rowstride)

def color_parse(*args) -> Gdk.Color:
    try:
        v = Gdk.RGBA()
        ok = v.parse(*args)
        if not ok:
            return None
        return v.to_color()
    except:
        ok, v = Gdk.Color.parse(*args)
    if not ok:
        return None
    return v

def get_default_root_window() -> Gdk.Window:
    screen = Gdk.Screen.get_default()
    if screen is None:
        return None
    return screen.get_root_window()

def get_root_size():
    if WIN32 or (POSIX and not OSX):
        #FIXME: hopefully, we can remove this code once GTK3 on win32 is fixed?
        #we do it the hard way because the root window geometry is invalid on win32:
        #and even just querying it causes this warning:
        #"GetClientRect failed: Invalid window handle."
        screen = Gdk.Screen.get_default()
        if screen is None:
            return 1920, 1024
        w = screen.get_width()
        h = screen.get_height()
    else:
        #the easy way for platforms that work out of the box:
        root = get_default_root_window()
        w, h = root.get_geometry()[2:4]
    if w<=0 or h<=0 or w>32768 or h>32768:
        if first_time("Gtk root window dimensions"):
            log.warn("Warning: Gdk returned invalid root window dimensions: %ix%i", w, h)
            w, h = 1920, 1080
            log.warn(" using %ix%i instead", w, h)
            if WIN32:
                log.warn(" no access to the display?")
    return w, h

def get_default_cursor() -> Gdk.Cursor:
    display = Gdk.Display.get_default()
    return Gdk.Cursor.new_from_name(display, "default")

BUTTON_MASK = {
    Gdk.ModifierType.BUTTON1_MASK : 1,
    Gdk.ModifierType.BUTTON2_MASK : 2,
    Gdk.ModifierType.BUTTON3_MASK : 3,
    Gdk.ModifierType.BUTTON4_MASK : 4,
    Gdk.ModifierType.BUTTON5_MASK : 5,
    }

em = Gdk.EventMask
WINDOW_EVENT_MASK = em.STRUCTURE_MASK | em.KEY_PRESS_MASK | em.KEY_RELEASE_MASK \
        | em.POINTER_MOTION_MASK | em.BUTTON_PRESS_MASK | em.BUTTON_RELEASE_MASK \
        | em.PROPERTY_CHANGE_MASK | em.SCROLL_MASK
del em

WINDOW_NAME_TO_HINT = {
            "NORMAL"        : Gdk.WindowTypeHint.NORMAL,
            "DIALOG"        : Gdk.WindowTypeHint.DIALOG,
            "MENU"          : Gdk.WindowTypeHint.MENU,
            "TOOLBAR"       : Gdk.WindowTypeHint.TOOLBAR,
            "SPLASH"        : Gdk.WindowTypeHint.SPLASHSCREEN,
            "UTILITY"       : Gdk.WindowTypeHint.UTILITY,
            "DOCK"          : Gdk.WindowTypeHint.DOCK,
            "DESKTOP"       : Gdk.WindowTypeHint.DESKTOP,
            "DROPDOWN_MENU" : Gdk.WindowTypeHint.DROPDOWN_MENU,
            "POPUP_MENU"    : Gdk.WindowTypeHint.POPUP_MENU,
            "TOOLTIP"       : Gdk.WindowTypeHint.TOOLTIP,
            "NOTIFICATION"  : Gdk.WindowTypeHint.NOTIFICATION,
            "COMBO"         : Gdk.WindowTypeHint.COMBO,
            "DND"           : Gdk.WindowTypeHint.DND
            }

orig_pack_start = Gtk.Box.pack_start
def pack_start(self, child, expand=True, fill=True, padding=0):
    orig_pack_start(self, child, expand, fill, padding)
Gtk.Box.pack_start = pack_start

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


def get_screens_info() -> dict:
    display = Gdk.Display.get_default()
    info = {}
    for i in range(display.get_n_screens()):
        screen = display.get_screen(i)
        info[i] = get_screen_info(display, screen)
    return info

def get_screen_sizes(xscale=1, yscale=1):
    from xpra.platform.gui import get_workarea, get_workareas
    def xs(v):
        return iround(v/xscale)
    def ys(v):
        return iround(v/yscale)
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
        return int(size_pixels * 254 / size_mm / 10)
    n_screens = display.get_n_screens()
    get_n_monitors = getattr(display, "get_n_monitors", None)
    if get_n_monitors:
        #GTK 3.22: always just one screen
        n_monitors = get_n_monitors()
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
            if manufacturer and model:
                plug_name = "%s %s" % (manufacturer, model)
            elif manufacturer:
                plug_name = manufacturer
            elif model:
                plug_name = model
            else:
                plug_name = "%i" % j
            wmm, hmm = monitor.get_width_mm(), monitor.get_height_mm()
            monitor = [plug_name, xs(geom.x), ys(geom.y), xs(geom.width), ys(geom.height), wmm, hmm]
            screenlog(" monitor %s: %s", j, monitor)
            if workareas:
                w = workareas[j]
                monitor += list(swork(*w))
            monitors.append(tuple(monitor))
        screen = display.get_default_screen()
        sw, sh = screen.get_width(), screen.get_height()
        work_x, work_y, work_width, work_height = swork(0, 0, sw, sh)
        workarea = get_workarea()   #pylint: disable=assignment-from-none
        if workarea:
            work_x, work_y, work_width, work_height = swork(*workarea)  #pylint: disable=not-an-iterable
        screenlog(" workarea=%s", workarea)
        wmm = screen.get_width_mm()
        hmm = screen.get_height_mm()
        xdpi = dpi(sw, wmm)
        ydpi = dpi(sh, hmm)
        if xdpi<MIN_DPI or xdpi>MAX_DPI or ydpi<MIN_DPI or ydpi>MAX_DPI:
            warn = first_time("invalid-screen-size-%ix%i" % (wmm, hmm))
            if warn:
                log.warn("Warning: ignoring invalid screen size %ix%imm", wmm, hmm)
            if n_monitors>0:
                wmm = sum(display.get_monitor(i).get_width_mm() for i in range(n_monitors))
                hmm = sum(display.get_monitor(i).get_height_mm() for i in range(n_monitors))
                xdpi = dpi(sw, wmm)
                ydpi = dpi(sh, hmm)
            if xdpi<MIN_DPI or xdpi>MAX_DPI or ydpi<MIN_DPI or ydpi>MAX_DPI:
                #still invalid, generate one from DPI=96
                wmm = iround(sw*25.4/96)
                hmm = iround(sh*25.4/96)
            if warn:
                log.warn(" using %ix%i mm", wmm, hmm)
        item = (screen.make_display_name(), xs(sw), ys(sh),
                    wmm, hmm,
                    monitors,
                    work_x, work_y, work_width, work_height)
        screenlog(" screen: %s", item)
        screen_sizes = [item]
    else:
        i=0
        screen_sizes = []
        #GTK2 or GTK3<3.22:
        screenlog("get_screen_sizes(%f, %f) found %s screens", xscale, yscale, n_screens)
        while i<n_screens:
            screen = display.get_screen(i)
            j = 0
            monitors = []
            workareas = []
            #native "get_workareas()" is only valid for a single screen (but describes all the monitors)
            #and it is only implemented on win32 right now
            #other platforms only implement "get_workarea()" instead, which is reported against the screen
            n_monitors = screen.get_n_monitors()
            screenlog(" screen %s has %s monitors", i, n_monitors)
            if n_screens==1:
                workareas = get_workareas()
                if workareas and len(workareas)!=n_monitors:
                    screenlog(" workareas: %s", workareas)
                    screenlog(" number of monitors does not match number of workareas!")
                    workareas = []
            while j<screen.get_n_monitors():
                geom = screen.get_monitor_geometry(j)
                plug_name = ""
                if hasattr(screen, "get_monitor_plug_name"):
                    plug_name = screen.get_monitor_plug_name(j) or ""
                wmm = -1
                if hasattr(screen, "get_monitor_width_mm"):
                    wmm = screen.get_monitor_width_mm(j)
                hmm = -1
                if hasattr(screen, "get_monitor_height_mm"):
                    hmm = screen.get_monitor_height_mm(j)
                monitor = [plug_name, xs(geom.x), ys(geom.y), xs(geom.width), ys(geom.height), wmm, hmm]
                screenlog(" monitor %s: %s", j, monitor)
                if workareas:
                    w = workareas[j]
                    monitor += list(swork(*w))
                monitors.append(tuple(monitor))
                j += 1
            work_x, work_y, work_width, work_height = swork(0, 0, screen.get_width(), screen.get_height())
            workarea = get_workarea()   #pylint: disable=assignment-from-none
            if workarea:
                work_x, work_y, work_width, work_height = swork(*workarea)  #pylint: disable=not-an-iterable
            screenlog(" workarea=%s", workarea)
            item = (screen.make_display_name(), xs(screen.get_width()), ys(screen.get_height()),
                        screen.get_width_mm(), screen.get_height_mm(),
                        monitors,
                        work_x, work_y, work_width, work_height)
            screenlog(" screen %s: %s", i, item)
            screen_sizes.append(item)
            i += 1
    return screen_sizes

def get_screen_info(display, screen) -> dict:
    info = {}
    if not WIN32:
        try:
            w = screen.get_root_window()
            info["root"] = w.get_geometry()
        except:
            pass
    info["name"] = screen.make_display_name()
    for x in ("width", "height", "width_mm", "height_mm", "resolution", "primary_monitor"):
        fn = getattr(screen, "get_"+x)
        try:
            info[x] = int(fn())
        except:
            pass
    info["monitors"] = screen.get_n_monitors()
    m_info = info.setdefault("monitor", {})
    for i in range(screen.get_n_monitors()):
        m_info[i] = get_monitor_info(display, screen, i)
    try:
        fo = screen.get_font_options()
        #win32 and osx return nothing here...
        if fo:
            fontoptions = info.setdefault("fontoptions", {})
            for x,vdict in {
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
                    },
                }.items():
                fn = getattr(fo, "get_"+x)
                val = fn()
                fontoptions[x] = vdict.get(val, val)
    except:
        pass
    vinfo = info.setdefault("visual", {})
    def visual(name, v):
        if not v:
            return
        for x, vdict in {
            "bits_per_rgb"          : {},
            "byte_order"            : BYTE_ORDER_NAMES,
            "colormap_size"         : {},
            "depth"                 : {},
            "red_pixel_details"     : {},
            "green_pixel_details"   : {},
            "blue_pixel_details"    : {},
            "visual_type"           : VISUAL_NAMES,
            }.items():
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
                vinfo.setdefault(name, {})[x] = vdict.get(val, val)
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

def get_monitor_info(_display, screen, i) -> dict:
    info = {}
    geom = screen.get_monitor_geometry(i)
    for x in ("x", "y", "width", "height"):
        info[x] = getattr(geom, x)
    if hasattr(screen, "get_monitor_plug_name"):
        info["plug_name"] = screen.get_monitor_plug_name(i) or ""
    for x in ("scale_factor", "width_mm", "height_mm"):
        try:
            fn = getattr(screen, "get_monitor_"+x)
            info[x] = int(fn(i))
        except:
            pass
    if hasattr(screen, "get_monitor_workarea"): #GTK3.4:
        rectangle = screen.get_monitor_workarea(i)
        workarea_info = info.setdefault("workarea", {})
        for x in ("x", "y", "width", "height"):
            workarea_info[x] = getattr(rectangle, x)
    return info


def get_display_info() -> dict:
    display = Gdk.Display.get_default()
    info = {
            "root-size"             : get_root_size(),
            "screens"               : display.get_n_screens(),
            "name"                  : display.get_name(),
            "pointer"               : display.get_pointer()[-3:-1],
            "devices"               : len(display.list_devices()),
            "default_cursor_size"   : display.get_default_cursor_size(),
            "maximal_cursor_size"   : display.get_maximal_cursor_size(),
            "pointer_is_grabbed"    : display.pointer_is_grabbed(),
            }
    if not WIN32:
        info["root"] = get_default_root_window().get_geometry()
    sinfo = info.setdefault("supports", {})
    for x in ("composite", "cursor_alpha", "cursor_color", "selection_notification", "clipboard_persistence", "shapes"):
        f = "supports_"+x
        if hasattr(display, f):
            fn = getattr(display, f)
            sinfo[x]  = fn()
    info["screens"] = get_screens_info()
    dm = display.get_device_manager()
    for dt, name in {Gdk.DeviceType.MASTER  : "master",
                     Gdk.DeviceType.SLAVE   : "slave",
                     Gdk.DeviceType.FLOATING: "floating"}.items():
        dinfo = info.setdefault("device", {})
        dtinfo = dinfo.setdefault(name, {})
        devices = dm.list_devices(dt)
        for i, d in enumerate(devices):
            dtinfo[i] = d.get_name()
    return info


def scaled_image(pixbuf, icon_size=None) -> Gtk.Image:
    if not pixbuf:
        return None
    if icon_size:
        pixbuf = pixbuf.scale_simple(icon_size, icon_size, GdkPixbuf.InterpType.BILINEAR)
    return Gtk.Image.new_from_pixbuf(pixbuf)


def get_icon_from_file(filename):
    try:
        if not os.path.exists(filename):
            log.warn("Warning: cannot load icon, '%s' does not exist", filename)
            return None
        with open(filename, mode='rb') as f:
            data = f.read()
        loader = GdkPixbuf.PixbufLoader()
        loader.write(data)
        loader.close()
    except Exception as e:
        log("get_icon_from_file(%s)", filename, exc_info=True)
        log.error("Error: failed to load '%s'", filename)
        log.error(" %s", e)
        return None
    pixbuf = loader.get_pixbuf()
    return pixbuf


def imagebutton(title, icon, tooltip=None, clicked_callback=None, icon_size=32,
                default=False, min_size=None, label_color=None, label_font=None) -> Gtk.Button:
    button = Gtk.Button(title)
    settings = button.get_settings()
    settings.set_property('gtk-button-images', True)
    if icon:
        if icon_size:
            icon = scaled_image(icon, icon_size)
        button.set_image(icon)
    if tooltip:
        button.set_tooltip_text(tooltip)
    if min_size:
        button.set_size_request(min_size, min_size)
    if clicked_callback:
        button.connect("clicked", clicked_callback)
    if default:
        button.set_can_default(True)
    if label_color or label_font:
        try:
            alignment = button.get_children()[0]
            b_hbox = alignment.get_children()[0]
            label = b_hbox.get_children()[1]
        except IndexError:
            pass
        else:
            if label_color:
                label.modify_fg(Gtk.StateType.NORMAL, label_color)
            if label_font:
                label.modify_font(label_font)
    return button

def menuitem(title, image=None, tooltip=None, cb=None) -> Gtk.ImageMenuItem:
    """ Utility method for easily creating an ImageMenuItem """
    menu_item = Gtk.ImageMenuItem()
    menu_item.set_label(title)
    if image:
        menu_item.set_image(image)
        #override gtk defaults: we *want* icons:
        settings = menu_item.get_settings()
        settings.set_property('gtk-menu-images', True)
        if hasattr(menu_item, "set_always_show_image"):
            menu_item.set_always_show_image(True)
    if tooltip:
        menu_item.set_tooltip_text(tooltip)
    if cb:
        menu_item.connect('activate', cb)
    menu_item.show()
    return menu_item


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


def label(text="", tooltip=None, font=None) -> Gtk.Label:
    l = Gtk.Label(text)
    if font:
        fontdesc = Pango.FontDescription(font)
        l.modify_font(fontdesc)
    if tooltip:
        l.set_tooltip_text(tooltip)
    return l


class TableBuilder:

    def __init__(self, rows=1, columns=2, homogeneous=False, col_spacings=0, row_spacings=0):
        self.table = Gtk.Table(rows, columns, homogeneous)
        self.table.set_col_spacings(col_spacings)
        self.table.set_row_spacings(row_spacings)
        self.row = 0
        self.widget_xalign = 0.0

    def get_table(self):
        return self.table

    def add_row(self, label, *widgets, **kwargs):
        if label:
            l_al = Gtk.Alignment(xalign=1.0, yalign=0.5, xscale=0.0, yscale=0.0)
            l_al.add(label)
            self.attach(l_al, 0)
        if widgets:
            i = 1
            for w in widgets:
                if w:
                    w_al = Gtk.Alignment(xalign=self.widget_xalign, yalign=0.5, xscale=0.0, yscale=0.0)
                    w_al.add(w)
                    self.attach(w_al, i, **kwargs)
                i += 1
        self.inc()

    def attach(self, widget, i, count=1, xoptions=Gtk.AttachOptions.FILL, yoptions=Gtk.AttachOptions.FILL, xpadding=10, ypadding=0):
        self.table.attach(widget, i, i+count, self.row, self.row+1,
                          xoptions=xoptions, yoptions=yoptions, xpadding=xpadding, ypadding=ypadding)

    def inc(self):
        self.row += 1

    def new_row(self, row_label_str, value1, value2=None, label_tooltip=None, **kwargs):
        row_label = label(row_label_str, label_tooltip)
        self.add_row(row_label, value1, value2, **kwargs)


def choose_files(parent_window, title, action=Gtk.FileChooserAction.OPEN, action_button=Gtk.STOCK_OPEN, callback=None, file_filter=None, multiple=True):
    log("choose_files%s", (parent_window, title, action, action_button, callback, file_filter))
    chooser = Gtk.FileChooserDialog(title,
                                parent=parent_window, action=action,
                                buttons=(Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL, action_button, Gtk.ResponseType.OK))
    chooser.set_select_multiple(multiple)
    chooser.set_default_response(Gtk.ResponseType.OK)
    if file_filter:
        chooser.add_filter(file_filter)
    response = chooser.run()
    filenames = chooser.get_filenames()
    chooser.hide()
    chooser.destroy()
    if response!=Gtk.ResponseType.OK:
        return None
    return filenames

def choose_file(parent_window, title, action=Gtk.FileChooserAction.OPEN, action_button=Gtk.STOCK_OPEN, callback=None, file_filter=None):
    filenames = choose_files(parent_window, title, action, action_button, callback, file_filter, False)
    if not filenames or len(filenames)!=1:
        return None
    filename = filenames[0]
    if callback:
        callback(filename)
    return filename


def main():
    from xpra.platform import program_context
    from xpra.log import enable_color
    with program_context("GTK-Version-Info", "GTK Version Info"):
        enable_color()
        print("%s" % get_gtk_version_info())


if __name__ == "__main__":
    main()
