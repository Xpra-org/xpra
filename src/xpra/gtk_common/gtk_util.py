# coding=utf8
# This file is part of Xpra.
# Copyright (C) 2011-2017 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os.path
import array
from xpra.util import iround
from xpra.os_util import strtobytes, WIN32
from xpra.gtk_common.gobject_compat import import_gtk, import_gdk, import_glib, import_pixbufloader, import_pango, import_cairo, import_gobject, import_pixbuf, is_gtk3
gtk     = import_gtk()
gdk     = import_gdk()
pango   = import_pango()
cairo   = import_cairo()
gobject = import_gobject()
PixbufLoader = import_pixbufloader()
Pixbuf = import_pixbuf()

from xpra.log import Logger
log = Logger("gtk", "util")
traylog = Logger("gtk", "tray")
screenlog = Logger("gtk", "screen")


SHOW_ALL_VISUALS = False

GTK_VERSION_INFO = {}
def get_gtk_version_info():
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
        V("gobject",    gobject,    "pygobject_version")

        if is_gtk3():
            #this isn't the actual version, (only shows as "3.0")
            #but still better than nothing:
            import gi
            V("gi",         gi,         "__version__")
            V("gtk",        gtk,        "_version")
            V("gdk",        gdk,        "_version")
            V("gobject",    gobject,    "_version")
            V("pixbuf",     Pixbuf,     "_version")

            av("pygtk", "n/a")
            V("pixbuf",     Pixbuf,     "PIXBUF_VERSION")
            try:
                v = [getattr(gtk, x) for x in ["MAJOR_VERSION", "MICRO_VERSION", "MINOR_VERSION"]]
                av("gtk", ".".join(str(x) for x in v))
            except:
                pass
        else:
            V("pygtk",      gtk,        "pygtk_version")
            V("gtk",        gtk,        "gtk_version")
            V("gdk",        gdk,        "__version__")

        #from here on, the code is the same for both GTK2 and GTK3, hooray:
        vfn = getattr(cairo, "cairo_version_string", None)
        if vfn:
            av("cairo", vfn())
        vfn = getattr(pango, "version_string")
        if vfn:
            av("pango", vfn())
        glib = import_glib()
        V("glib",       glib,       "glib_version")
        V("pyglib",     glib,       "pyglib_version")
    return GTK_VERSION_INFO.copy()


def popup_menu_workaround(*args):
    #only implemented with GTK2 on win32 below
    pass


if is_gtk3():
    def is_realized(widget):
        return widget.get_realized()

    def get_pixbuf_from_data(rgb_data, has_alpha, w, h, rowstride):
        data = array.array('B', strtobytes(rgb_data))
        return GdkPixbuf.Pixbuf.new_from_data(data, GdkPixbuf.Colorspace.RGB,
                                         True, 8, w, h, rowstride,
                                         None, None)

    def get_preferred_size(widget):
        #ignore "min", we only care about "natural":
        _, w = widget.get_preferred_width()
        _, h = widget.get_preferred_height()
        return w, h

    def color_parse(*args):
        ok, v = gdk.Color.parse(*args)
        if not ok:
            return None
        return v
    def get_xwindow(w):
        return w.get_xid()
    def get_default_root_window():
        return gdk.Screen.get_default().get_root_window()
    def get_root_size():
        if WIN32:
            #FIXME: hopefully, we can remove this code once GTK3 on win32 is fixed?
            #we do it the hard way because the root window geometry is invalid on win32:
            #and even just querying it causes this warning:
            #"GetClientRect failed: Invalid window handle."
            display = gdk.Display.get_default()
            n = display.get_n_screens()
            w, h = 0, 0
            for i in range(n):
                screen = display.get_screen(i)
                w += screen.get_width()
                h += screen.get_height()
        else:
            #the easy way for platforms that work out of the box:
            root = get_default_root_window()
            w, h = root.get_geometry()[2:4]
        if w<=0 or h<=0 or w>32768 or h>32768:
            log.warn("Warning: Gdk returned invalid root window dimensions: %ix%i", w, h)
            w, h = 1920, 1080
            log.warn(" using %ix%i instead", w, h)
        return w, h

    keymap_get_for_display  = gdk.Keymap.get_for_display

    def get_default_cursor():
        return gdk.Cursor.new(gdk.CursorType.X_CURSOR)
    new_Cursor_for_display  = gdk.Cursor.new_for_display
    new_Cursor_from_pixbuf  = gdk.Cursor.new_from_pixbuf
    from gi.repository import GdkPixbuf     #@UnresolvedImport
    image_new_from_pixbuf   = gtk.Image.new_from_pixbuf
    pixbuf_new_from_file    = GdkPixbuf.Pixbuf.new_from_file
    window_set_default_icon = gtk.Window.set_default_icon
    icon_theme_get_default  = gtk.IconTheme.get_default

    def gdk_cairo_context(cairo_context):
        return cairo_context
    def pixbuf_new_from_data(*args):
        args = list(args)+[None, None]
        return GdkPixbuf.Pixbuf.new_from_data(*args)
    get_default_keymap      = gdk.Keymap.get_default
    display_get_default     = gdk.Display.get_default
    screen_get_default      = gdk.Screen.get_default
    cairo_set_source_pixbuf = gdk.cairo_set_source_pixbuf
    COLORSPACE_RGB          = GdkPixbuf.Colorspace.RGB
    INTERP_HYPER    = GdkPixbuf.InterpType.HYPER
    INTERP_BILINEAR = GdkPixbuf.InterpType.BILINEAR
    RELIEF_NONE     = gtk.ReliefStyle.NONE
    RELIEF_NORMAL   = gtk.ReliefStyle.NORMAL
    FILL            = gtk.AttachOptions.FILL
    EXPAND          = gtk.AttachOptions.EXPAND
    STATE_NORMAL    = gtk.StateType.NORMAL
    WIN_POS_CENTER  = gtk.WindowPosition.CENTER
    RESPONSE_CANCEL = gtk.ResponseType.CANCEL
    RESPONSE_OK     = gtk.ResponseType.OK
    WINDOW_TOPLEVEL = gdk.WindowType.TOPLEVEL
    FILE_CHOOSER_ACTION_SAVE    = gtk.FileChooserAction.SAVE
    FILE_CHOOSER_ACTION_OPEN    = gtk.FileChooserAction.OPEN
    PROPERTY_CHANGE_MASK = gdk.EventMask.PROPERTY_CHANGE_MASK
    BUTTON_PRESS_MASK    = gdk.EventMask.BUTTON_PRESS_MASK
    ACCEL_LOCKED = gtk.AccelFlags.LOCKED
    ACCEL_VISIBLE = gtk.AccelFlags.VISIBLE
    JUSTIFY_LEFT    = gtk.Justification.LEFT
    JUSTIFY_RIGHT   = gtk.Justification.RIGHT
    POINTER_MOTION_MASK         = gdk.EventMask.POINTER_MOTION_MASK
    POINTER_MOTION_HINT_MASK    = gdk.EventMask.POINTER_MOTION_HINT_MASK
    MESSAGE_INFO    = gtk.MessageType.INFO
    MESSAGE_QUESTION= gtk.MessageType.QUESTION
    BUTTONS_CLOSE   = gtk.ButtonsType.CLOSE
    BUTTONS_NONE    = gtk.ButtonsType.NONE
    DIALOG_DESTROY_WITH_PARENT  = 0

    WINDOW_POPUP    = gtk.WindowType.POPUP
    WINDOW_TOPLEVEL = gtk.WindowType.TOPLEVEL

    LSB_FIRST       = gdk.ByteOrder.LSB_FIRST
    MSB_FIRST       = gdk.ByteOrder.MSB_FIRST
    STATIC_GRAY     = gdk.VisualType.STATIC_GRAY
    GRAYSCALE       = gdk.VisualType.GRAYSCALE
    STATIC_COLOR    = gdk.VisualType.STATIC_COLOR
    PSEUDO_COLOR    = gdk.VisualType.PSEUDO_COLOR
    TRUE_COLOR      = gdk.VisualType.TRUE_COLOR
    DIRECT_COLOR    = gdk.VisualType.DIRECT_COLOR

    SCROLL_UP       = gdk.ScrollDirection.UP
    SCROLL_DOWN     = gdk.ScrollDirection.DOWN
    SCROLL_LEFT     = gdk.ScrollDirection.LEFT
    SCROLL_RIGHT    = gdk.ScrollDirection.RIGHT

    mt = gdk.ModifierType
    SHIFT_MASK      = mt.SHIFT_MASK
    LOCK_MASK       = mt.LOCK_MASK
    META_MASK       = mt.META_MASK
    CONTROL_MASK    = mt.CONTROL_MASK
    MOD1_MASK       = mt.MOD1_MASK
    MOD2_MASK       = mt.MOD2_MASK
    MOD3_MASK       = mt.MOD3_MASK
    MOD4_MASK       = mt.MOD4_MASK
    MOD5_MASK       = mt.MOD5_MASK

    BUTTON_MASK = {mt.BUTTON1_MASK : 1,
                   mt.BUTTON2_MASK : 2,
                   mt.BUTTON3_MASK : 3,
                   mt.BUTTON4_MASK : 4,
                   mt.BUTTON5_MASK : 5}
    del mt

    em = gdk.EventMask
    KEY_PRESS_MASK = em.KEY_PRESS_MASK
    WINDOW_EVENT_MASK = em.STRUCTURE_MASK | em.KEY_PRESS_MASK | em.KEY_RELEASE_MASK \
            | em.POINTER_MOTION_MASK | em.BUTTON_PRESS_MASK | em.BUTTON_RELEASE_MASK \
            | em.PROPERTY_CHANGE_MASK | em.SCROLL_MASK
    del em

    WINDOW_NAME_TO_HINT = {
                "NORMAL"        : gdk.WindowTypeHint.NORMAL,
                "DIALOG"        : gdk.WindowTypeHint.DIALOG,
                "MENU"          : gdk.WindowTypeHint.MENU,
                "TOOLBAR"       : gdk.WindowTypeHint.TOOLBAR,
                "SPLASH"        : gdk.WindowTypeHint.SPLASHSCREEN,
                "UTILITY"       : gdk.WindowTypeHint.UTILITY,
                "DOCK"          : gdk.WindowTypeHint.DOCK,
                "DESKTOP"       : gdk.WindowTypeHint.DESKTOP,
                "DROPDOWN_MENU" : gdk.WindowTypeHint.DROPDOWN_MENU,
                "POPUP_MENU"    : gdk.WindowTypeHint.POPUP_MENU,
                "TOOLTIP"       : gdk.WindowTypeHint.TOOLTIP,
                "NOTIFICATION"  : gdk.WindowTypeHint.NOTIFICATION,
                "COMBO"         : gdk.WindowTypeHint.COMBO,
                "DND"           : gdk.WindowTypeHint.DND
                }

    GRAB_SUCCESS        = gdk.GrabStatus.SUCCESS
    ALREADY_GRABBED     = gdk.GrabStatus.ALREADY_GRABBED
    GRAB_INVALID_TIME   = gdk.GrabStatus.INVALID_TIME
    GRAB_NOT_VIEWABLE   = gdk.GrabStatus.NOT_VIEWABLE
    GRAB_FROZEN         = gdk.GrabStatus.FROZEN

    from gi.repository.Gtk import Clipboard     #@UnresolvedImport
    CLIPBOARD_SELECTION = {}
    #gtk2: uses strings:
    for x in ("PRIMARY", "SECONDARY", "CLIPBOARD"):
        CLIPBOARD_SELECTION[x] = getattr(gdk, "SELECTION_%s" % x)
    def GetClipboard(selection):
        return Clipboard.get(CLIPBOARD_SELECTION[selection])

    #copied from pygtkcompat - I wished I had found this earlier..
    orig_pack_end = gtk.Box.pack_end
    def pack_end(self, child, expand=True, fill=True, padding=0):
        orig_pack_end(self, child, expand, fill, padding)
    gtk.Box.pack_end = pack_end
    orig_pack_start = gtk.Box.pack_start
    def pack_start(self, child, expand=True, fill=True, padding=0):
        orig_pack_start(self, child, expand, fill, padding)
    gtk.Box.pack_start = pack_start
    gtk.combo_box_new_text = gtk.ComboBoxText

    class OptionMenu(gtk.MenuButton):
        pass

    gdk_window_process_all_updates = gdk.Window.process_all_updates
    def gtk_main():
        gdk.threads_init()
        try:
            gdk.threads_enter()
            gtk.main()
        finally:
            gdk.threads_leave()

else:
    def get_pixbuf_from_data(rgb_data, has_alpha, w, h, rowstride):
        return gdk.pixbuf_new_from_data(rgb_data, gdk.COLORSPACE_RGB, has_alpha, 8, w, h, rowstride)

    def get_preferred_size(widget):
        return widget.size_request()

    def get_xwindow(w):
        return w.xid
    #gtk2:
    if gtk.gtk_version<(2,18):
        raise Exception("your version of GTK is too old: %s" % str(gtk.gtk_version))
    if gtk.pygtk_version<(2,16):
        raise Exception("your version of PyGTK is too old: %s" % str(gtk.pygtk_version))

    if not hasattr(gtk.Widget, "get_realized"):
        def is_realized(widget):
            return widget.flags() & gtk.REALIZED
    else:
        def is_realized(widget):
            return widget.get_realized()

    get_default_root_window = gdk.get_default_root_window
    def get_root_size():
        return get_default_root_window().get_size()
    keymap_get_for_display  = gdk.keymap_get_for_display

    def get_default_cursor():
        return gdk.Cursor(gdk.X_CURSOR)
    color_parse             = gdk.color_parse
    new_Cursor_for_display  = gdk.Cursor
    new_Cursor_from_pixbuf  = gdk.Cursor
    image_new_from_pixbuf   = gtk.image_new_from_pixbuf
    pixbuf_new_from_file    = gdk.pixbuf_new_from_file
    pixbuf_new_from_data    = gdk.pixbuf_new_from_data
    get_default_keymap      = gdk.keymap_get_default
    display_get_default     = gdk.display_get_default
    screen_get_default      = gdk.screen_get_default
    window_set_default_icon = gtk.window_set_default_icon
    icon_theme_get_default  = gtk.icon_theme_get_default

    def gdk_cairo_context(cairo_context):
        return gdk.CairoContext(cairo_context)
    def cairo_set_source_pixbuf(cr, pixbuf, x, y):
        cr.set_source_pixbuf(pixbuf, x, y)
    COLORSPACE_RGB          = gdk.COLORSPACE_RGB
    INTERP_HYPER    = gdk.INTERP_HYPER
    INTERP_BILINEAR = gdk.INTERP_BILINEAR
    RELIEF_NONE     = gtk.RELIEF_NONE
    RELIEF_NORMAL   = gtk.RELIEF_NORMAL
    FILL            = gtk.FILL
    EXPAND          = gtk.EXPAND
    STATE_NORMAL    = gtk.STATE_NORMAL
    WIN_POS_CENTER  = gtk.WIN_POS_CENTER
    RESPONSE_CANCEL = gtk.RESPONSE_CANCEL
    RESPONSE_OK     = gtk.RESPONSE_OK
    WINDOW_TOPLEVEL = gdk.WINDOW_TOPLEVEL
    FILE_CHOOSER_ACTION_SAVE    = gtk.FILE_CHOOSER_ACTION_SAVE
    FILE_CHOOSER_ACTION_OPEN    = gtk.FILE_CHOOSER_ACTION_OPEN
    PROPERTY_CHANGE_MASK = gdk.PROPERTY_CHANGE_MASK
    BUTTON_PRESS_MASK    = gdk.BUTTON_PRESS_MASK
    ACCEL_LOCKED = gtk.ACCEL_LOCKED
    ACCEL_VISIBLE = gtk.ACCEL_VISIBLE
    JUSTIFY_LEFT    = gtk.JUSTIFY_LEFT
    JUSTIFY_RIGHT   = gtk.JUSTIFY_RIGHT
    POINTER_MOTION_MASK         = gdk.POINTER_MOTION_MASK
    POINTER_MOTION_HINT_MASK    = gdk.POINTER_MOTION_HINT_MASK
    MESSAGE_INFO    = gtk.MESSAGE_INFO
    MESSAGE_QUESTION= gtk.MESSAGE_QUESTION
    BUTTONS_CLOSE   = gtk.BUTTONS_CLOSE
    BUTTONS_NONE    = gtk.BUTTONS_NONE
    DIALOG_DESTROY_WITH_PARENT = gtk.DIALOG_DESTROY_WITH_PARENT

    WINDOW_POPUP    = gtk.WINDOW_POPUP
    WINDOW_TOPLEVEL = gtk.WINDOW_TOPLEVEL

    LSB_FIRST       = gdk.LSB_FIRST
    MSB_FIRST       = gdk.MSB_FIRST
    STATIC_GRAY     = gdk.VISUAL_STATIC_GRAY
    GRAYSCALE       = gdk.VISUAL_GRAYSCALE
    STATIC_COLOR    = gdk.VISUAL_STATIC_COLOR
    PSEUDO_COLOR    = gdk.VISUAL_PSEUDO_COLOR
    TRUE_COLOR      = gdk.VISUAL_TRUE_COLOR
    DIRECT_COLOR    = gdk.VISUAL_DIRECT_COLOR

    SCROLL_UP       = gdk.SCROLL_UP
    SCROLL_DOWN     = gdk.SCROLL_DOWN
    SCROLL_LEFT     = gdk.SCROLL_LEFT
    SCROLL_RIGHT    = gdk.SCROLL_RIGHT

    SHIFT_MASK      = gdk.SHIFT_MASK
    LOCK_MASK       = gdk.LOCK_MASK
    META_MASK       = gdk.META_MASK
    CONTROL_MASK    = gdk.CONTROL_MASK
    MOD1_MASK       = gdk.MOD1_MASK
    MOD2_MASK       = gdk.MOD2_MASK
    MOD3_MASK       = gdk.MOD3_MASK
    MOD4_MASK       = gdk.MOD4_MASK
    MOD5_MASK       = gdk.MOD5_MASK

    BUTTON_MASK = {gdk.BUTTON1_MASK : 1,
                   gdk.BUTTON2_MASK : 2,
                   gdk.BUTTON3_MASK : 3,
                   gdk.BUTTON4_MASK : 4,
                   gdk.BUTTON5_MASK : 5}

    KEY_PRESS_MASK = gdk.KEY_PRESS_MASK
    WINDOW_EVENT_MASK = gdk.STRUCTURE_MASK | gdk.KEY_PRESS_MASK | gdk.KEY_RELEASE_MASK \
            | gdk.POINTER_MOTION_MASK | gdk.BUTTON_PRESS_MASK | gdk.BUTTON_RELEASE_MASK \
            | gdk.PROPERTY_CHANGE_MASK

    WINDOW_NAME_TO_HINT = {
                "NORMAL"        : gdk.WINDOW_TYPE_HINT_NORMAL,
                "DIALOG"        : gdk.WINDOW_TYPE_HINT_DIALOG,
                "MENU"          : gdk.WINDOW_TYPE_HINT_MENU,
                "TOOLBAR"       : gdk.WINDOW_TYPE_HINT_TOOLBAR,
                "SPLASH"        : gdk.WINDOW_TYPE_HINT_SPLASHSCREEN,
                "UTILITY"       : gdk.WINDOW_TYPE_HINT_UTILITY,
                "DOCK"          : gdk.WINDOW_TYPE_HINT_DOCK,
                "DESKTOP"       : gdk.WINDOW_TYPE_HINT_DESKTOP,
                "DROPDOWN_MENU" : gdk.WINDOW_TYPE_HINT_DROPDOWN_MENU,
                "POPUP_MENU"    : gdk.WINDOW_TYPE_HINT_POPUP_MENU,
                "TOOLTIP"       : gdk.WINDOW_TYPE_HINT_TOOLTIP,
                "NOTIFICATION"  : gdk.WINDOW_TYPE_HINT_NOTIFICATION,
                "COMBO"         : gdk.WINDOW_TYPE_HINT_COMBO,
                "DND"           : gdk.WINDOW_TYPE_HINT_DND
                }

    GRAB_SUCCESS        = gdk.GRAB_SUCCESS
    ALREADY_GRABBED     = gdk.GRAB_ALREADY_GRABBED
    GRAB_INVALID_TIME   = gdk.GRAB_INVALID_TIME
    GRAB_NOT_VIEWABLE   = gdk.GRAB_NOT_VIEWABLE
    GRAB_FROZEN         = gdk.GRAB_FROZEN

    OptionMenu  = gtk.OptionMenu

    def GetClipboard(selection):
        return gtk.Clipboard(selection=selection)

    gdk_window_process_all_updates = gdk.window_process_all_updates
    def gtk_main():
        if gtk.main_level()==0:
            gdk.threads_init()
            try:
                gdk.threads_enter()
                gtk.main()
            finally:
                gdk.threads_leave()

    if WIN32:
        mouse_in_tray_menu_counter = 0
        mouse_in_tray_menu = False
        OUTSIDE_TRAY_TIMEOUT = 500
        def popup_menu_workaround(menu, close_cb):
            """ MS Windows does not automatically close the popup menu when we click outside it
                so we workaround it by using a timer and closing the menu when the mouse
                has stayed outside it for more than OUTSIDE_TRAY_TIMEOUT (0.5s).
                This code must be added to all the sub-menus of the popup menu too!
            """
            global mouse_in_tray_menu, mouse_in_tray_menu_counter
            def enter_menu(*_args):
                global mouse_in_tray_menu, mouse_in_tray_menu_counter
                traylog("mouse_in_tray_menu=%s", mouse_in_tray_menu)
                mouse_in_tray_menu_counter += 1
                mouse_in_tray_menu = True
            def leave_menu(*_args):
                global mouse_in_tray_menu, mouse_in_tray_menu_counter
                traylog("mouse_in_tray_menu=%s", mouse_in_tray_menu)
                mouse_in_tray_menu_counter += 1
                mouse_in_tray_menu = False
                def check_menu_left(expected_counter):
                    if mouse_in_tray_menu:
                        return    False
                    if expected_counter!=mouse_in_tray_menu_counter:
                        return    False            #counter has changed
                    close_cb()
                gobject.timeout_add(OUTSIDE_TRAY_TIMEOUT, check_menu_left, mouse_in_tray_menu_counter)
            mouse_in_tray_menu_counter = 0
            mouse_in_tray_menu = False
            traylog("popup_menu_workaround: adding events callbacks")
            menu.connect("enter-notify-event", enter_menu)
            menu.connect("leave-notify-event", leave_menu)
        def gtk_main():
            gtk.main()

GRAB_STATUS_STRING = {
                      GRAB_SUCCESS          : "SUCCESS",
                      ALREADY_GRABBED       : "ALREADY_GRABBED",
                      GRAB_INVALID_TIME     : "INVALID_TIME",
                      GRAB_NOT_VIEWABLE     : "NOT_VIEWABLE",
                      GRAB_FROZEN           : "FROZEN",
                      }


class TrayCheckMenuItem(gtk.CheckMenuItem):
    """ We add a button handler to catch clicks that somehow do not
        trigger the "toggled" signal on some platforms (win32?) when we
        show the tray menu with a right click and click on the item with the left click.
        (or the other way around?)
    """
    def __init__(self, label, tooltip=None):
        gtk.CheckMenuItem.__init__(self, label)
        self.label = label
        if tooltip:
            self.set_tooltip_text(tooltip)
        self.add_events(BUTTON_PRESS_MASK)
        self.connect("button-release-event", self.on_button_release_event)

    def on_button_release_event(self, *args):
        traylog("TrayCheckMenuItem.on_button_release_event(%s) label=%s", args, self.label)
        self.active_state = self.get_active()
        def recheck():
            traylog("TrayCheckMenuItem: recheck() active_state=%s, get_active()=%s", self.active_state, self.get_active())
            state = self.active_state
            self.active_state = None
            if state is not None and state==self.get_active():
                #toggle did not fire after the button release, so force it:
                self.set_active(not state)
        gobject.idle_add(recheck)

CheckMenuItemClass = gtk.CheckMenuItem
def CheckMenuItem(*args, **kwargs):
    global CheckMenuItemClass
    return CheckMenuItemClass(*args, **kwargs)

def set_use_tray_workaround(enabled):
    global CheckMenuItemClass
    if enabled:
        CheckMenuItemClass = TrayCheckMenuItem
    else:
        CheckMenuItemClass = gtk.CheckMenuItem
set_use_tray_workaround(True)



def get_screens_info():
    display = display_get_default()
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
    display = display_get_default()
    i=0
    screen_sizes = []
    n_screens = display.get_n_screens()
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
        workarea = get_workarea()
        if workarea:
            work_x, work_y, work_width, work_height = swork(*workarea)
        screenlog(" workarea=%s", workarea)
        item = (screen.make_display_name(), xs(screen.get_width()), ys(screen.get_height()),
                    screen.get_width_mm(), screen.get_height_mm(),
                    monitors,
                    work_x, work_y, work_width, work_height)
        screenlog(" screen %s: %s", i, item)
        screen_sizes.append(item)
        i += 1
    return screen_sizes

def get_screen_info(display, screen):
    info = {}
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
        import cairo
        fo = screen.get_font_options()
        #win32 and osx return nothing here...
        if fo:
            fontoptions = info.setdefault("fontoptions", {})
            for x,vdict in {
                            "antialias"     : {cairo.ANTIALIAS_DEFAULT      : "default", cairo.ANTIALIAS_NONE       : "none",   cairo.ANTIALIAS_GRAY        : "gray",   cairo.ANTIALIAS_SUBPIXEL    : "subpixel"},
                            "hint_metrics"  : {cairo.HINT_METRICS_DEFAULT   : "default", cairo.HINT_METRICS_OFF     : "off",    cairo.HINT_METRICS_ON       : "on"},
                            "hint_style"    : {cairo.HINT_STYLE_DEFAULT     : "default", cairo.HINT_STYLE_NONE      : "none",   cairo.HINT_STYLE_SLIGHT     : "slight", cairo.HINT_STYLE_MEDIUM     : "medium", cairo.HINT_STYLE_FULL       : "full"},
                            "subpixel_order": {cairo.SUBPIXEL_ORDER_DEFAULT : "default", cairo.SUBPIXEL_ORDER_RGB   : "RGB",    cairo.SUBPIXEL_ORDER_BGR    : "BGR",    cairo.SUBPIXEL_ORDER_VRGB   : "VRGB",   cairo.SUBPIXEL_ORDER_VBGR   : "VBGR"},
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
        for x, vdict in {"bits_per_rgb" : {},
                         "byte_order"   : {LSB_FIRST    : "LSB", MSB_FIRST  : "MSB"},
                         "colormap_size": {},
                         "depth"        : {},
                         "red_pixel_details"    : {},
                         "green_pixel_details"  : {},
                         "blue_pixel_details"   : {},
                         "visual_type"  : {STATIC_GRAY : "STATIC_GRAY", GRAYSCALE : "GRAYSCALE",  STATIC_COLOR : "STATIC_COLOR", PSEUDO_COLOR : "PSEUDO_COLOR", TRUE_COLOR : "TRUE_COLOR", DIRECT_COLOR : "DIRECT_COLOR"},
                         }.items():
            val = None
            try:
                val = getattr(v, x.replace("visual_"))  #ugly workaround for "visual_type" -> "type" for GTK2...
            except:
                try:
                    fn = getattr(v, "get_"+x)
                    val = fn()
                except:
                    pass
            if val is not None:
                vinfo.setdefault(name, {})[x] = vdict.get(val, val)
    try:
        visual("rgb", screen.get_rgb_visual())
    except:
        pass    #not in gtk3?
    visual("rgba", screen.get_rgba_visual())
    visual("system_visual", screen.get_system_visual())
    if SHOW_ALL_VISUALS:
        for i, v in enumerate(screen.list_visuals()):
            visual(i, v)
    #gtk.settings
    if is_gtk3():
        def get_setting(key):
            #try string first, then int
            for t in (gobject.TYPE_STRING, gobject.TYPE_INT):
                v = gobject.Value()
                v.init(t)
                if screen.get_setting(key, v):
                    return v.get_value()
            return None
    else:
        settings = gtk.settings_get_for_screen(screen)
        def get_setting(key):
            return settings.get_property(key)
    sinfo = info.setdefault("settings", {})
    try:
        for x in ("antialias", "dpi", "hinting", "hintstyle", "rgba"):
            try:
                v = get_setting("gtk-xft-"+x)
            except:
                continue
            if v is None:
                v = ""
            sinfo[x] = v
    except:
        pass
    return info

def get_monitor_info(display, screen, i):
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


def get_display_info():
    display = display_get_default()
    info = {
            "root"                  : get_default_root_window().get_geometry(),
            "root-size"             : get_root_size(),
            "screens"               : display.get_n_screens(),
            "name"                  : display.get_name(),
            "pointer"               : display.get_pointer()[1:3],
            "devices"               : len(display.list_devices()),
            "default_cursor_size"   : display.get_default_cursor_size(),
            "maximal_cursor_size"   : display.get_maximal_cursor_size(),
            "pointer_is_grabbed"    : display.pointer_is_grabbed(),
            }
    sinfo = info.setdefault("supports", {})
    for x in ("composite", "cursor_alpha", "cursor_color", "selection_notification", "clipboard_persistence", "shapes"):
        f = "supports_"+x
        if hasattr(display, f):
            fn = getattr(display, f)
            sinfo[x]  = fn()
    info["screens"] = get_screens_info()
    if is_gtk3():
        dm = display.get_device_manager()
        for dt, name in {gdk.DeviceType.MASTER  : "master",
                         gdk.DeviceType.SLAVE   : "slave",
                         gdk.DeviceType.FLOATING: "floating"}.items():
            dinfo = info.setdefault("device", {})
            dtinfo = dinfo.setdefault(name, {})
            devices = dm.list_devices(dt)
            for i, d in enumerate(devices):
                dtinfo[i] = d.get_name()
    else:
        devices = display.list_devices()
        for i, d in enumerate(devices):
            dinfo = info.setdefault("device", {}).setdefault(i, {})
            dinfo[""] = d.get_name()
            AXES_STR = {
                        gdk.AXIS_IGNORE         : "IGNORE",
                        gdk.AXIS_X              : "X",
                        gdk.AXIS_Y              : "Y",
                        gdk.AXIS_PRESSURE       : "PRESSURE",
                        gdk.AXIS_XTILT          : "XTILT",
                        gdk.AXIS_YTILT          : "YTILT",
                        gdk.AXIS_WHEEL          : "WHEEL",
                        gdk.AXIS_LAST           : "LAST",
                        }
            MODE_STR = {
                        gdk.MODE_DISABLED       : "DISABLED",
                        gdk.MODE_SCREEN         : "SCREEN",
                        gdk.MODE_WINDOW         : "WINDOW",
                        }
            SOURCE_STR = {
                        gdk.SOURCE_MOUSE        : "MOUSE",
                        gdk.SOURCE_PEN          : "PEN",
                        gdk.SOURCE_ERASER       : "ERASER",
                        gdk.SOURCE_CURSOR       : "CURSOR",
                        }
            def notrans(v, _d):
                return v
            MOD_STR = {
                        gdk.SHIFT_MASK          : "SHIFT",
                        gdk.LOCK_MASK           : "LOCK",
                        gdk.CONTROL_MASK        : "CONTROL",
                        gdk.META_MASK           : "META",
                        gdk.MOD1_MASK           : "MOD1",
                        gdk.MOD2_MASK           : "MOD2",
                        gdk.MOD3_MASK           : "MOD3",
                        gdk.MOD4_MASK           : "MOD4",
                        gdk.MOD5_MASK           : "MOD5",
                        gdk.BUTTON1_MASK        : "BUTTON1",
                        gdk.BUTTON2_MASK        : "BUTTON2",
                        gdk.BUTTON3_MASK        : "BUTTON3",
                        gdk.BUTTON4_MASK        : "BUTTON4",
                        gdk.BUTTON5_MASK        : "BUTTON5",
                        gdk.RELEASE_MASK        : "RELEASE",
                       }
            def modtrans(mod):
                return [v for k,v in MOD_STR.items() if k&mod]
            def keys_trans(l, _d):
                #GdkModifierType can be converted to an int
                return [(k,modtrans(v)) for (k,v) in l]
            for name, trans in {"axes"          : AXES_STR.get,
                                "has_cursor"    : notrans,
                                "keys"          : keys_trans,
                                "mode"          : MODE_STR.get,
                                "num_axes"      : notrans,
                                "num_keys"      : notrans,
                                "source"        : SOURCE_STR.get}.items():
                try:
                    v = getattr(d, name)
                    dinfo[name] = trans(v, v)
                except:
                    pass
    return info


def scaled_image(pixbuf, icon_size=None):
    if icon_size:
        pixbuf = pixbuf.scale_simple(icon_size, icon_size, INTERP_BILINEAR)
    return image_new_from_pixbuf(pixbuf)



def get_icon_from_file(filename):
    try:
        if not os.path.exists(filename):
            log.warn("%s does not exist", filename)
            return    None
        with open(filename, mode='rb') as f:
            data = f.read()
        loader = PixbufLoader()
        loader.write(data)
        loader.close()
    except Exception as e:
        log("get_icon_from_file(%s)", filename, exc_info=True)
        log.error("Error: failed to load '%s'", filename)
        log.error(" %s", e)
        return None
    pixbuf = loader.get_pixbuf()
    return pixbuf


def imagebutton(title, icon, tooltip=None, clicked_callback=None, icon_size=32, default=False, min_size=None, label_color=None):
    button = gtk.Button(title)
    settings = button.get_settings()
    settings.set_property('gtk-button-images', True)
    if icon:
        button.set_image(scaled_image(icon, icon_size))
    if tooltip:
        button.set_tooltip_text(tooltip)
    if min_size:
        button.set_size_request(min_size, min_size)
    if clicked_callback:
        button.connect("clicked", clicked_callback)
    if default:
        if is_gtk3():
            button.set_can_default(True)
        else:
            button.set_flags(gtk.CAN_DEFAULT)
    if label_color:
        alignment = button.get_children()[0]
        b_hbox = alignment.get_children()[0]
        label = b_hbox.get_children()[1]
        label.modify_fg(STATE_NORMAL, label_color)
    return button

def menuitem(title, image=None, tooltip=None, cb=None):
    """ Utility method for easily creating an ImageMenuItem """
    menu_item = gtk.ImageMenuItem(title)
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
    if is_gtk3():
        def connect(ag, *args):
            ag.connect(*args)
    else:
        def connect(ag, *args):
            ag.connect_group(*args)
    accel_group = gtk.AccelGroup()
    key, mod = gtk.accelerator_parse('<control>F4')
    connect(accel_group, key, mod, ACCEL_LOCKED, callback)
    window.add_accel_group(accel_group)
    accel_group = gtk.AccelGroup()
    key, mod = gtk.accelerator_parse('<Alt>F4')
    connect(accel_group, key, mod, ACCEL_LOCKED, callback)
    escape_key, modifier = gtk.accelerator_parse('Escape')
    connect(accel_group, escape_key, modifier, ACCEL_LOCKED |  ACCEL_VISIBLE, callback)
    window.add_accel_group(accel_group)


def label(text="", tooltip=None, font=None):
    l = gtk.Label(text)
    if font:
        fontdesc = pango.FontDescription(font)
        l.modify_font(fontdesc)
    if tooltip:
        l.set_tooltip_text(tooltip)
    return l


def title_box(label_str):
    eb = gtk.EventBox()
    l = label(label_str)
    l.modify_fg(STATE_NORMAL, gdk.Color(red=48*256, green=0, blue=0))
    al = gtk.Alignment(xalign=0.0, yalign=0.5, xscale=0.0, yscale=0.0)
    al.set_padding(0, 0, 10, 10)
    al.add(l)
    eb.add(al)
    eb.modify_bg(STATE_NORMAL, gdk.Color(red=219*256, green=226*256, blue=242*256))
    return eb



#utility method to ensure there is always only one CheckMenuItem
#selected in a submenu:
def ensure_item_selected(submenu, item, recurse=True):
    if not isinstance(item, gtk.CheckMenuItem):
        return
    if item.get_active():
        #deactivate all except this one
        def deactivate(items, skip=None):
            for x in items:
                if x==skip:
                    continue
                if isinstance(x, gtk.MenuItem):
                    submenu = x.get_submenu()
                    if submenu and recurse:
                        deactivate(submenu.get_children(), skip)
                if isinstance(x, gtk.CheckMenuItem):
                    if x!=item and x.get_active():
                        x.set_active(False)
        deactivate(submenu.get_children(), item)
        return item
    #ensure there is at least one other active item
    def get_active_item(items):
        for x in items:
            if isinstance(x, gtk.MenuItem):
                submenu = x.get_submenu()
                if submenu:
                    a = get_active_item(submenu.get_children())
                    if a:
                        return a
            if isinstance(x, gtk.CheckMenuItem):
                if x.get_active():
                    return x
        return None
    active = get_active_item(submenu.get_children())
    if active:
        return  active
    #if not then keep this one active:
    item.set_active(True)
    return item


class TableBuilder(object):

    def __init__(self, rows=1, columns=2, homogeneous=False, col_spacings=0, row_spacings=0):
        self.table = gtk.Table(rows, columns, homogeneous)
        self.table.set_col_spacings(col_spacings)
        self.table.set_row_spacings(row_spacings)
        self.row = 0
        self.widget_xalign = 0.0

    def get_table(self):
        return self.table

    def add_row(self, label, *widgets, **kwargs):
        if label:
            l_al = gtk.Alignment(xalign=1.0, yalign=0.5, xscale=0.0, yscale=0.0)
            l_al.add(label)
            self.attach(l_al, 0)
        if widgets:
            i = 1
            for w in widgets:
                if w:
                    w_al = gtk.Alignment(xalign=self.widget_xalign, yalign=0.5, xscale=0.0, yscale=0.0)
                    w_al.add(w)
                    self.attach(w_al, i, **kwargs)
                i += 1
        self.inc()

    def attach(self, widget, i, count=1, xoptions=FILL, yoptions=FILL, xpadding=10, ypadding=0):
        self.table.attach(widget, i, i+count, self.row, self.row+1, xoptions=xoptions, yoptions=yoptions, xpadding=xpadding, ypadding=ypadding)

    def inc(self):
        self.row += 1

    def new_row(self, row_label_str, value1, value2=None, label_tooltip=None, **kwargs):
        row_label = label(row_label_str, label_tooltip)
        self.add_row(row_label, value1, value2, **kwargs)


def choose_file(parent_window, title, action, action_button, callback, file_filter=None):
    log("choose_file%s", (parent_window, title, action, action_button, callback, file_filter))
    chooser = gtk.FileChooserDialog(title,
                                parent=parent_window, action=action,
                                buttons=(gtk.STOCK_CANCEL, RESPONSE_CANCEL, action_button, RESPONSE_OK))
    chooser.set_select_multiple(False)
    chooser.set_default_response(RESPONSE_OK)
    if file_filter:
        chooser.add_filter(file_filter)
    response = chooser.run()
    filenames = chooser.get_filenames()
    chooser.hide()
    chooser.destroy()
    if response!=RESPONSE_OK or len(filenames)!=1:
        return
    filename = filenames[0]
    callback(filename)
