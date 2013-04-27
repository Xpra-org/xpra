# coding=utf8
# This file is part of Xpra.
# Copyright (C) 2011-2013 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os.path

from xpra.gobject_compat import import_gtk, import_gdk, import_gobject, is_gtk3
gtk = import_gtk()
gdk = import_gdk()
gobject = import_gobject()

from xpra.log import Logger
log = Logger()


def add_gtk_version_info(props, gtk):
    if hasattr(gtk, "pygtk_version"):
        props["pygtk_version"] = gtk.pygtk_version
    if hasattr(gtk, "gtk_version"):
        props["gtk_version"] = gtk.gtk_version
    elif hasattr(gtk, "_version"):
        props["gtk_version"] = gtk._version


def scaled_image(pixbuf, icon_size):
    return    gtk.image_new_from_pixbuf(pixbuf.scale_simple(icon_size, icon_size, gdk.INTERP_BILINEAR))


def get_icon_from_file(filename):
    try:
        if not os.path.exists(filename):
            log.warn("%s does not exist", filename)
            return    None
        f = open(filename, mode='rb')
        data = f.read()
        f.close()
        loader = gdk.PixbufLoader()
        loader.write(data)
        loader.close()
    except Exception, e:
        log.error("get_icon_from_file(%s) %s", filename, e)
        return    None
    pixbuf = loader.get_pixbuf()
    return pixbuf


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


def label(text="", tooltip=None):
    l = gtk.Label(text)
    if tooltip:
        set_tooltip_text(l, tooltip)
    return l


def title_box(label_str):
    eb = gtk.EventBox()
    l = label(label_str)
    l.modify_fg(gtk.STATE_NORMAL, gdk.Color(red=48*256, green=0, blue=0))
    al = gtk.Alignment(xalign=0.0, yalign=0.5, xscale=0.0, yscale=0.0)
    al.set_padding(0, 0, 10, 10)
    al.add(l)
    eb.add(al)
    eb.modify_bg(gtk.STATE_NORMAL, gdk.Color(red=219*256, green=226*256, blue=242*256))
    return eb


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

    def attach(self, widget, i, count=1, xoptions=gtk.FILL, xpadding=10):
        self.table.attach(widget, i, i+count, self.row, self.row+1, xoptions=xoptions, xpadding=xpadding)

    def inc(self):
        self.row += 1

    def new_row(self, row_label_str, value1, value2=None, label_tooltip=None):
        row_label = label(row_label_str, label_tooltip)
        self.add_row(row_label, value1, value2)
