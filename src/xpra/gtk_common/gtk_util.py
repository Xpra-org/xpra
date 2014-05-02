# coding=utf8
# This file is part of Xpra.
# Copyright (C) 2011-2014 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys
import os.path

from xpra.gtk_common.gobject_compat import import_gtk, import_gdk, import_pixbufloader, import_pango, is_gtk3
gtk = import_gtk()
gdk = import_gdk()
pango = import_pango()
PixbufLoader = import_pixbufloader()

from xpra.log import Logger
log = Logger("gtk", "util")

GTK_VERSION_INFO = {}
if hasattr(gtk, "pygtk_version"):
    GTK_VERSION_INFO["pygtk_version"] = gtk.pygtk_version
if hasattr(gtk, "gtk_version"):
    #GTK2:
    GTK_VERSION_INFO["gtk_version"] = gtk.gtk_version
elif hasattr(gtk, "_version"):
    #GTK3:
    GTK_VERSION_INFO["gtk_version"] = gtk._version
if hasattr(gdk, "__version__"):
    #GTK2:
    GTK_VERSION_INFO["gdk_version"] = gdk.__version__
elif hasattr(gdk, "_version"):
    #GTK3:
    GTK_VERSION_INFO["gdk_version"] = gdk._version
    try:
        import gi
        GTK_VERSION_INFO["gi_repository_version"] = gi.__version__
    except:
        pass


if is_gtk3():
    #where is this gone now?
    from gi.repository import GdkPixbuf     #@UnresolvedImport
    image_new_from_pixbuf = gtk.Image.new_from_pixbuf
    INTERP_HYPER    = GdkPixbuf.InterpType.HYPER
    INTERP_BILINEAR = GdkPixbuf.InterpType.BILINEAR
    RELIEF_NONE     = gtk.ReliefStyle.NONE
    RELIEF_NORMAL   = gtk.ReliefStyle.NORMAL
    FILL            = gtk.AttachOptions.FILL
    EXPAND          = gtk.AttachOptions.EXPAND
    STATE_NORMAL    = gtk.StateType.NORMAL
    WIN_POS_CENTER  = gtk.WindowPosition.CENTER
    get_default_keymap  = gdk.Keymap.get_default
else:
    image_new_from_pixbuf = gtk.image_new_from_pixbuf
    INTERP_HYPER    = gtk.gdk.INTERP_HYPER
    INTERP_BILINEAR = gdk.INTERP_BILINEAR
    RELIEF_NONE     = gtk.RELIEF_NONE
    RELIEF_NORMAL   = gtk.RELIEF_NORMAL
    FILL            = gtk.FILL
    EXPAND          = gtk.EXPAND
    STATE_NORMAL    = gtk.STATE_NORMAL
    WIN_POS_CENTER  = gtk.WIN_POS_CENTER
    get_default_keymap  = gdk.keymap_get_default


def add_gtk_version_info(props, gtk, prefix="", new_namespace=False):
    #update props given:
    global GTK_VERSION_INFO
    for k,v in GTK_VERSION_INFO.items():
        if new_namespace:
            k = k.replace("_", ".")
        props[prefix+k] = v


def get_preferred_size(widget):
    if is_gtk3():
        #ignore "min", we only care about "natural":
        _, w = widget.get_preferred_width()
        _, h = widget.get_preferred_height()
        return w, h
    return widget.size_request()

def scaled_image(pixbuf, icon_size):
    return image_new_from_pixbuf(pixbuf.scale_simple(icon_size, icon_size, INTERP_BILINEAR))


def get_pixbuf_from_data(rgb_data, has_alpha, w, h, rowstride):
    if is_gtk3():
        import array
        data = array.array('B', rgb_data)
        return GdkPixbuf.Pixbuf.new_from_data(data, GdkPixbuf.Colorspace.RGB,
                                         True, 8, w, h, rowstride,
                                         None, None)
    return gdk.pixbuf_new_from_data(rgb_data, gdk.COLORSPACE_RGB, has_alpha, 8, w, h, rowstride)


def get_icon_from_file(filename):
    try:
        if not os.path.exists(filename):
            log.warn("%s does not exist", filename)
            return    None
        f = open(filename, mode='rb')
        try:
            data = f.read()
        finally:
            f.close()
        loader = PixbufLoader()
        loader.write(data)
        loader.close()
    except:
        e = sys.exc_info()[1]
        log.error("get_icon_from_file(%s) %s", filename, e)
        return    None
    pixbuf = loader.get_pixbuf()
    return pixbuf


def imagebutton(title, icon, tooltip=None, clicked_callback=None, icon_size=32, default=False, min_size=None, label_color=None):
    button = gtk.Button(title)
    settings = button.get_settings()
    settings.set_property('gtk-button-images', True)
    if icon:
        button.set_image(scaled_image(icon, icon_size))
    if tooltip:
        set_tooltip_text(button, tooltip)
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
        set_tooltip_text(menu_item, tooltip)
    if cb:
        menu_item.connect('activate', cb)
    menu_item.show()
    return menu_item

def set_tooltip_text(widget, text):
    if hasattr(widget, "set_tooltip_text"):
        widget.set_tooltip_text(text)
        return True
    return False


def add_close_accel(window, callback):
    if is_gtk3():
        return      #TODO: implement accel for gtk3
    accel_group = gtk.AccelGroup()
    accel_group.connect_group(ord('w'), gdk.CONTROL_MASK, gtk.ACCEL_LOCKED, callback)
    window.add_accel_group(accel_group)
    accel_group = gtk.AccelGroup()
    key, mod = gtk.accelerator_parse('<Alt>F4')
    accel_group.connect_group(key, mod, gtk.ACCEL_LOCKED, callback)
    escape_key, modifier = gtk.accelerator_parse('Escape')
    accel_group.connect_group(escape_key, modifier, gtk.ACCEL_LOCKED |  gtk.ACCEL_VISIBLE, callback)
    window.add_accel_group(accel_group)


def label(text="", tooltip=None, font=None):
    l = gtk.Label(text)
    if font:
        fontdesc = pango.FontDescription(font)
        l.modify_font(fontdesc)
    if tooltip:
        set_tooltip_text(l, tooltip)
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
def ensure_item_selected(submenu, item):
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
                    if submenu:
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

def set_checkeditems(submenu, is_match_func):
    """ recursively descends a submenu and any of its sub menus
        and set any "CheckMenuItem" to active if is_match_func(item) """
    if submenu is None:
        return
    for x in submenu.get_children():
        if isinstance(x, gtk.MenuItem):
            set_checkeditems(x.get_submenu(), is_match_func)
        if isinstance(x, gtk.CheckMenuItem):
            a = x.get_active()
            v = is_match_func(x)
            if a!=v:
                x.set_active(v)


def CheckMenuItem(label, tooltip=None):
    """ adds a get_label() method for older versions of gtk which do not have it
        beware that this label is not mutable!
    """
    cmi = gtk.CheckMenuItem(label)
    if not hasattr(cmi, "get_label"):
        def get_label():
            return  label
        cmi.get_label = get_label
    if tooltip:
        set_tooltip_text(cmi, tooltip)
    return cmi


class TableBuilder(object):

    def __init__(self, rows=1, columns=2, homogeneous=False):
        self.table = gtk.Table(rows, columns, homogeneous)
        self.table.set_col_spacings(0)
        self.table.set_row_spacings(0)
        self.row = 0
        self.widget_xalign = 0.0

    def get_table(self):
        return self.table

    def add_row(self, label, *widgets):
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
                    self.attach(w_al, i)
                i += 1
        self.inc()

    def attach(self, widget, i, count=1, xoptions=FILL, xpadding=10):
        self.table.attach(widget, i, i+count, self.row, self.row+1, xoptions=xoptions, xpadding=xpadding)

    def inc(self):
        self.row += 1

    def new_row(self, row_label_str, value1, value2=None, label_tooltip=None):
        row_label = label(row_label_str, label_tooltip)
        self.add_row(row_label, value1, value2)
