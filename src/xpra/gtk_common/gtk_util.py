# -*- coding: utf-8 -*-
# This file is part of Xpra.
# Copyright (C) 2011-2019 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os.path
import array
import cairo
from gi.repository import GLib
from gi.repository import GdkPixbuf     #@UnresolvedImport
from gi.repository import Pango
from gi.repository import GObject

from xpra.util import iround, first_time
from xpra.os_util import (
    strtobytes, bytestostr,
    WIN32, OSX, POSIX,
    )
from xpra.gtk_common.gobject_compat import (
    import_gtk, import_gdk,
    )
from xpra.log import Logger

log = Logger("gtk", "util")
traylog = Logger("gtk", "tray")
screenlog = Logger("gtk", "screen")
alphalog = Logger("gtk", "alpha")

gtk     = import_gtk()
gdk     = import_gdk()

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
        V("gobject",    GObject,    "pygobject_version")

        #this isn't the actual version, (only shows as "3.0")
        #but still better than nothing:
        import gi
        V("gi",         gi,         "__version__")
        V("gtk",        gtk,        "_version")
        V("gdk",        gdk,        "_version")
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
        MAJORMICROMINOR("gtk",  gtk)
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


def pixbuf_save_to_memory(pixbuf, fmt="png"):
    buf = []
    def save_to_memory(data, *_args, **_kwargs):
        buf.append(strtobytes(data))
        return True
    pixbuf.save_to_callbackv(save_to_memory, None, fmt, [], [])
    return b"".join(buf)


def is_realized(widget):
    return widget.get_realized()

def x11_foreign_new(display, xid):
    from gi.repository import GdkX11
    return GdkX11.X11Window.foreign_new_for_display(display, xid)

def GDKWindow(parent=None, width=1, height=1, window_type=gdk.WindowType.TOPLEVEL,
              event_mask=0, wclass=gdk.WindowWindowClass.INPUT_OUTPUT, title=None,
              x=None, y=None, override_redirect=False, visual=None, **kwargs):
    attributes_mask = 0
    attributes = gdk.WindowAttr()
    if x is not None:
        attributes.x = x
        attributes_mask |= gdk.WindowAttributesType.X
    if y is not None:
        attributes.y = y
        attributes_mask |= gdk.WindowAttributesType.Y
    #attributes.type_hint = gdk.WindowTypeHint.NORMAL
    #attributes_mask |= gdk.WindowAttributesType.TYPE_HINT
    attributes.width = width
    attributes.height = height
    attributes.window_type = window_type
    if title:
        attributes.title = title
        attributes_mask |= gdk.WindowAttributesType.TITLE
    if visual:
        attributes.visual = visual
        attributes_mask |= gdk.WindowAttributesType.VISUAL
    #OR:
    attributes.override_redirect = override_redirect
    attributes_mask |= gdk.WindowAttributesType.NOREDIR
    #events:
    attributes.event_mask = event_mask
    #wclass:
    attributes.wclass = wclass
    mask = gdk.WindowAttributesType(attributes_mask)
    return gdk.Window(parent, attributes, mask)

def make_temp_window(title, window_type=gdk.WindowType.TEMP):
    return GDKWindow(title=title, window_type=window_type)

def enable_alpha(window):
    screen = window.get_screen()
    visual = screen.get_rgba_visual()
    alphalog("enable_alpha(%s) screen=%s, visual=%s", window, screen, visual)
    #we can't do alpha on win32 with plain GTK,
    #(though we handle it in the opengl backend)
    if WIN32:
        l = alphalog
    else:
        l = alphalog.error
    if visual is None or (not WIN32 and not screen.is_composited()):
        l("Error: cannot handle window transparency")
        if visual is None:
            l(" no RGBA visual")
        else:
            assert not screen.is_composited()
            l(" screen is not composited")
        return False
    alphalog("enable_alpha(%s) using rgba visual %s", window, visual)
    window.set_visual(visual)
    return True


def get_pixbuf_from_data(rgb_data, has_alpha, w, h, rowstride):
    data = array.array('B', strtobytes(rgb_data))
    return GdkPixbuf.Pixbuf.new_from_data(data, GdkPixbuf.Colorspace.RGB,
                                     has_alpha, 8, w, h, rowstride,
                                     None, None)


get_pixbuf_from_window = gdk.pixbuf_get_from_window

def get_preferred_size(widget):
    #ignore "min", we only care about "natural":
    _, w = widget.get_preferred_width()
    _, h = widget.get_preferred_height()
    return w, h

def color_parse(*args):
    try:
        v = gdk.RGBA()
        ok = v.parse(*args)
        if not ok:
            return None
        return v.to_color()
    except:
        ok, v = gdk.Color.parse(*args)
    if not ok:
        return None
    return v
def get_xwindow(w):
    return w.get_xid()
def get_default_root_window():
    screen = gdk.Screen.get_default()
    if screen is None:
        return None
    return screen.get_root_window()
def get_root_size():
    if WIN32 or (POSIX and not OSX):
        #FIXME: hopefully, we can remove this code once GTK3 on win32 is fixed?
        #we do it the hard way because the root window geometry is invalid on win32:
        #and even just querying it causes this warning:
        #"GetClientRect failed: Invalid window handle."
        screen = gdk.Screen.get_default()
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
    return w, h

keymap_get_for_display  = gdk.Keymap.get_for_display

def get_default_cursor():
    display = gdk.Display.get_default()
    return gdk.Cursor.new_from_name(display, "default")
new_Cursor_for_display  = gdk.Cursor.new_for_display
new_Cursor_from_pixbuf  = gdk.Cursor.new_from_pixbuf
image_new_from_pixbuf   = gtk.Image.new_from_pixbuf
pixbuf_new_from_file    = GdkPixbuf.Pixbuf.new_from_file
window_set_default_icon = gtk.Window.set_default_icon
icon_theme_get_default  = gtk.IconTheme.get_default
image_new_from_stock    = gtk.Image.new_from_stock

def gdk_cairo_context(cairo_context):
    return cairo_context
def pixbuf_new_from_data(*args):
    args = list(args)+[None, None]
    return GdkPixbuf.Pixbuf.new_from_data(*args)
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
RESPONSE_REJECT = gtk.ResponseType.REJECT
RESPONSE_ACCEPT = gtk.ResponseType.ACCEPT
RESPONSE_CLOSE  = gtk.ResponseType.CLOSE
RESPONSE_DELETE_EVENT = gtk.ResponseType.DELETE_EVENT


WINDOW_STATE_WITHDRAWN  = gdk.WindowState.WITHDRAWN
WINDOW_STATE_ICONIFIED  = gdk.WindowState.ICONIFIED
WINDOW_STATE_MAXIMIZED  = gdk.WindowState.MAXIMIZED
WINDOW_STATE_STICKY     = gdk.WindowState.STICKY
WINDOW_STATE_FULLSCREEN = gdk.WindowState.FULLSCREEN
WINDOW_STATE_ABOVE      = gdk.WindowState.ABOVE
WINDOW_STATE_BELOW      = gdk.WindowState.BELOW
FILE_CHOOSER_ACTION_SAVE    = gtk.FileChooserAction.SAVE
FILE_CHOOSER_ACTION_OPEN    = gtk.FileChooserAction.OPEN
PROPERTY_CHANGE_MASK = gdk.EventMask.PROPERTY_CHANGE_MASK
FOCUS_CHANGE_MASK    = gdk.EventMask.FOCUS_CHANGE_MASK
BUTTON_PRESS_MASK    = gdk.EventMask.BUTTON_PRESS_MASK
BUTTON_RELEASE_MASK  = gdk.EventMask.BUTTON_RELEASE_MASK
ENTER_NOTIFY_MASK    = gdk.EventMask.ENTER_NOTIFY_MASK
LEAVE_NOTIFY_MASK    = gdk.EventMask.LEAVE_NOTIFY_MASK
SUBSTRUCTURE_MASK    = gdk.EventMask.SUBSTRUCTURE_MASK
STRUCTURE_MASK       = gdk.EventMask.STRUCTURE_MASK
EXPOSURE_MASK        = gdk.EventMask.EXPOSURE_MASK
ACCEL_LOCKED = gtk.AccelFlags.LOCKED
ACCEL_VISIBLE = gtk.AccelFlags.VISIBLE
JUSTIFY_LEFT    = gtk.Justification.LEFT
JUSTIFY_RIGHT   = gtk.Justification.RIGHT
POINTER_MOTION_MASK         = gdk.EventMask.POINTER_MOTION_MASK
POINTER_MOTION_HINT_MASK    = gdk.EventMask.POINTER_MOTION_HINT_MASK
MESSAGE_ERROR   = gtk.MessageType.ERROR
MESSAGE_INFO    = gtk.MessageType.INFO
MESSAGE_QUESTION= gtk.MessageType.QUESTION
BUTTONS_CLOSE   = gtk.ButtonsType.CLOSE
BUTTONS_OK_CANCEL = gtk.ButtonsType.OK_CANCEL
BUTTONS_NONE    = gtk.ButtonsType.NONE
ICON_SIZE_BUTTON = gtk.IconSize.BUTTON

WINDOW_POPUP    = gtk.WindowType.POPUP
WINDOW_TOPLEVEL = gtk.WindowType.TOPLEVEL

GDKWINDOW_TEMP     = gdk.WindowType.TEMP
GDKWINDOW_TOPLEVEL = gdk.WindowType.TOPLEVEL
GDKWINDOW_CHILD    = gdk.WindowType.CHILD
GDKWINDOW_FOREIGN  = gdk.WindowType.FOREIGN

CLASS_INPUT_OUTPUT = gdk.WindowWindowClass.INPUT_OUTPUT
CLASS_INPUT_ONLY = gdk.WindowWindowClass.INPUT_ONLY

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

ORIENTATION_HORIZONTAL = gtk.Orientation.HORIZONTAL
ORIENTATION_VERTICAL = gtk.Orientation.VERTICAL

DIALOG_MODAL = gtk.DialogFlags.MODAL
DESTROY_WITH_PARENT = gtk.DialogFlags.DESTROY_WITH_PARENT

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
SUPER_MASK      = mt.SUPER_MASK
HYPER_MASK      = mt.HYPER_MASK

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

DEST_DEFAULT_MOTION     = gtk.DestDefaults.MOTION
DEST_DEFAULT_HIGHLIGHT  = gtk.DestDefaults.HIGHLIGHT
DEST_DEFAULT_DROP       = gtk.DestDefaults.DROP
DEST_DEFAULT_ALL        = gtk.DestDefaults.ALL
ACTION_COPY = gdk.DragAction.COPY
newTargetEntry = gtk.TargetEntry.new
def drag_status(context, action, time):
    gdk.drag_status(context, action, time)
def drag_context_targets(context):
    return list(x.name() for x in context.list_targets())
def drag_context_actions(context):
    return context.get_actions()
def drag_dest_window(context):
    return context.get_dest_window()
def drag_widget_get_data(widget, context, target, time):
    atom = gdk.Atom.intern(target, False)
    widget.drag_get_data(context, atom, time)

from gi.repository.Gtk import Clipboard     #@UnresolvedImport
def GetClipboard(selection):
    sstr = bytestostr(selection)
    atom = getattr(gdk, "SELECTION_%s" % sstr, None) or gdk.Atom.intern(sstr, False)
    return Clipboard.get(atom)
def clipboard_request_contents(clipboard, target, unpack):
    target_atom = gdk.Atom.intern(bytestostr(target), False)
    clipboard.request_contents(target_atom, unpack)

def selection_owner_set(widget, selection, time=0):
    selection_atom = gdk.Atom.intern(bytestostr(selection), False)
    return gtk.selection_owner_set(widget, selection_atom, time)
def selection_add_target(widget, selection, target, info=0):
    selection_atom = gdk.Atom.intern(bytestostr(selection), False)
    target_atom = gdk.Atom.intern(bytestostr(target), False)
    gtk.selection_add_target(widget, selection_atom, target_atom, info)
def selectiondata_get_selection(selectiondata):
    return selectiondata.get_selection().name()
def selectiondata_get_target(selectiondata):
    return selectiondata.get_target().name()
def selectiondata_get_data_type(selectiondata):
    return selectiondata.get_data_type()
def selectiondata_get_format(selectiondata):
    return selectiondata.get_format()
def selectiondata_get_data(selectiondata):
    return selectiondata.get_data()
def selectiondata_set(selectiondata, dtype, dformat, data):
    type_atom = gdk.Atom.intern(bytestostr(dtype), False)
    return selectiondata.set(type_atom, dformat, data)

def atom_intern(atom_name, only_if_exits=False):
    return gdk.Atom.intern(bytestostr(atom_name), only_if_exits)

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
    def set_menu(self, menu):
        return self.set_popup(menu)
    def get_menu(self):
        return self.get_popup()

gdk_window_process_all_updates = gdk.Window.process_all_updates
gtk_main = gtk.main

def popup_menu_workaround(*args):
    #only implemented with GTK2 on win32 below
    pass

def gio_File(path):
    from gi.repository import Gio   #@UnresolvedImport
    return Gio.File.new_for_path(path)

def query_info_async(gfile, attributes, callback, flags=0, cancellable=None):
    G_PRIORITY_DEFAULT = 0
    gfile.query_info_async(attributes, flags, G_PRIORITY_DEFAULT, cancellable, callback, None)

def load_contents_async(gfile, callback, cancellable=None, user_data=None):
    gfile.load_contents_async(cancellable, callback, user_data)

def load_contents_finish(gfile, res):
    _, data, etag = gfile.load_contents_finish(res)
    return data, len(data), etag

def set_clipboard_data(clipboard, thevalue, _vtype="STRING"):
    #only strings with GTK3?
    thestring = str(thevalue)
    clipboard.set_text(thestring, len(thestring))

def wait_for_contents(clipboard, target):
    atom = gdk.Atom.intern(target, False)
    return clipboard.wait_for_contents(atom)

PARAM_READABLE = GObject.ParamFlags.READABLE
PARAM_READWRITE = GObject.ParamFlags.READWRITE


#no idea why, but trying to use the threads_init / threads_enter
#causes deadlocks on win32:
if WIN32:
    gtk_main = gtk.main
gtk_main_quit = gtk.main_quit

GRAB_STATUS_STRING = {
                      GRAB_SUCCESS          : "SUCCESS",
                      ALREADY_GRABBED       : "ALREADY_GRABBED",
                      GRAB_INVALID_TIME     : "INVALID_TIME",
                      GRAB_NOT_VIEWABLE     : "NOT_VIEWABLE",
                      GRAB_FROZEN           : "FROZEN",
                      }

VISUAL_NAMES = {
    STATIC_GRAY      : "STATIC_GRAY",
    GRAYSCALE        : "GRAYSCALE",
    STATIC_COLOR     : "STATIC_COLOR",
    PSEUDO_COLOR     : "PSEUDO_COLOR",
    TRUE_COLOR       : "TRUE_COLOR",
    DIRECT_COLOR     : "DIRECT_COLOR",
    }

BYTE_ORDER_NAMES = {
                LSB_FIRST   : "LSB",
                MSB_FIRST   : "MSB",
                }


class TrayCheckMenuItem(gtk.CheckMenuItem):
    """ We add a button handler to catch clicks that somehow do not
        trigger the "toggled" signal on some platforms (win32?) when we
        show the tray menu with a right click and click on the item with the left click.
        (or the other way around)
    """
    def __init__(self, label, tooltip=None):
        gtk.CheckMenuItem.__init__(self)
        self.set_label(label)
        self.label = label
        if tooltip:
            self.set_tooltip_text(tooltip)
        self.add_events(BUTTON_PRESS_MASK)
        self.connect("button-release-event", self.on_button_release_event)

    def on_button_release_event(self, *args):
        traylog("TrayCheckMenuItem.on_button_release_event(%s) label=%s", args, self.label)
        self.active_state = self.get_active()
        def recheck():
            traylog("TrayCheckMenuItem: recheck() active_state=%s, get_active()=%s",
                    self.active_state, self.get_active())
            state = self.active_state
            self.active_state = None
            if state is not None and state==self.get_active():
                #toggle did not fire after the button release, so force it:
                self.set_active(not state)
        GLib.idle_add(recheck)

class TrayImageMenuItem(gtk.ImageMenuItem):
    """ We add a button handler to catch clicks that somehow do not
        trigger the "activate" signal on some platforms (win32?) when we
        show the tray menu with a right click and click on the item with the left click.
        (or the other way around)
    """
    def __init__(self):
        gtk.ImageMenuItem.__init__(self)
        self.add_events(BUTTON_RELEASE_MASK | BUTTON_PRESS_MASK)
        self.connect("button-release-event", self.on_button_release_event)
        self.connect("activate", self.record_activated)
        self._activated = False

    def record_activated(self, *args):
        traylog("record_activated%s", args)
        self._activated = True

    def on_button_release_event(self, *args):
        traylog("TrayImageMenuItem.on_button_release_event(%s) label=%s", args, self.get_label())
        self._activated = False
        def recheck():
            traylog("TrayImageMenuItem: recheck() already activated=%s", self._activated)
            if not self._activated:
                self.activate()
                #not essential since we'll clear it before calling recheck again:
                self._activated = False
        GLib.idle_add(recheck)


def CheckMenuItem(label):
    return gtk.CheckMenuItem(label=label)


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
    if not display:
        return ()
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
        item = (screen.make_display_name(), xs(sw), ys(sh),
                    screen.get_width_mm(), screen.get_height_mm(),
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

def get_screen_info(display, screen):
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
            "byte_order"            : {
                LSB_FIRST : "LSB",
                MSB_FIRST : "MSB",
            },
            "colormap_size"         : {},
            "depth"                 : {},
            "red_pixel_details"     : {},
            "green_pixel_details"   : {},
            "blue_pixel_details"    : {},
            "visual_type"           : {
                STATIC_GRAY    : "STATIC_GRAY",
                GRAYSCALE      : "GRAYSCALE",
                STATIC_COLOR   : "STATIC_COLOR",
                PSEUDO_COLOR   : "PSEUDO_COLOR",
                TRUE_COLOR     : "TRUE_COLOR",
                DIRECT_COLOR   : "DIRECT_COLOR",
                },
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
    def get_setting(key):
        #try string first, then int
        for t in (GObject.TYPE_STRING, GObject.TYPE_INT):
            v = GObject.Value()
            v.init(t)
            if screen.get_setting(key, v):
                return v.get_value()
        return None
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

def get_monitor_info(_display, screen, i):
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
    for dt, name in {gdk.DeviceType.MASTER  : "master",
                     gdk.DeviceType.SLAVE   : "slave",
                     gdk.DeviceType.FLOATING: "floating"}.items():
        dinfo = info.setdefault("device", {})
        dtinfo = dinfo.setdefault(name, {})
        devices = dm.list_devices(dt)
        for i, d in enumerate(devices):
            dtinfo[i] = d.get_name()
    return info


def scaled_image(pixbuf, icon_size=None):
    if not pixbuf:
        return None
    if icon_size:
        pixbuf = pixbuf.scale_simple(icon_size, icon_size, INTERP_BILINEAR)
    return image_new_from_pixbuf(pixbuf)



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


def set_tooltip_text(widget, text):
    #PITA: GTK3 has problems displaying tooltips:
    #makes it hard to click on the button!
    if not WIN32:
        widget.set_tooltip_text(text)


def imagebutton(title, icon, tooltip=None, clicked_callback=None, icon_size=32,
                default=False, min_size=None, label_color=None, label_font=None):
    button = gtk.Button(title)
    settings = button.get_settings()
    settings.set_property('gtk-button-images', True)
    if icon:
        if icon_size:
            icon = scaled_image(icon, icon_size)
        button.set_image(icon)
    if tooltip:
        set_tooltip_text(button, tooltip)
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
                label.modify_fg(STATE_NORMAL, label_color)
            if label_font:
                label.modify_font(label_font)
    return button

def menuitem(title, image=None, tooltip=None, cb=None):
    """ Utility method for easily creating an ImageMenuItem """
    menu_item = gtk.ImageMenuItem()
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

def add_window_accel(window, accel, callback):
    def connect(ag, *args):
        ag.connect(*args)
    accel_group = gtk.AccelGroup()
    key, mod = gtk.accelerator_parse(accel)
    connect(accel_group, key, mod, ACCEL_LOCKED, callback)
    window.add_accel_group(accel_group)
    return accel_group


def label(text="", tooltip=None, font=None):
    l = gtk.Label(text)
    if font:
        from gi.repository import Pango
        fontdesc = Pango.FontDescription(font)
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


def window_defaults(window):
    window.set_border_width(20)
    #window.modify_bg(STATE_NORMAL, gdk.Color(red=65535, green=65535, blue=65535))


#utility method to ensure there is always only one CheckMenuItem
#selected in a submenu:
def ensure_item_selected(submenu, item, recurse=True):
    if not isinstance(item, gtk.CheckMenuItem):
        return None
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
        return active
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
        self.table.attach(widget, i, i+count, self.row, self.row+1,
                          xoptions=xoptions, yoptions=yoptions, xpadding=xpadding, ypadding=ypadding)

    def inc(self):
        self.row += 1

    def new_row(self, row_label_str, value1, value2=None, label_tooltip=None, **kwargs):
        row_label = label(row_label_str, label_tooltip)
        self.add_row(row_label, value1, value2, **kwargs)


def choose_file(parent_window, title, action, action_button, callback=None, file_filter=None):
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
