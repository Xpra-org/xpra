# coding=utf8
# This file is part of Parti.
# Copyright (C) 2011-2013 Antoine Martin <antoine@devloop.org.uk>
# Parti is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os.path

from wimpiggy.gobject_compat import import_gtk, import_gdk, import_gobject, is_gtk3
gtk = import_gtk()
gdk = import_gdk()
gobject = import_gobject()

from wimpiggy.log import Logger
log = Logger()


def scaled_image(pixbuf, icon_size):
    return    gtk.image_new_from_pixbuf(pixbuf.scale_simple(icon_size,icon_size,gtk.gdk.INTERP_BILINEAR))


def get_icon_from_file(filename):
    try:
        if not os.path.exists(filename):
            log.warn("%s does not exist", filename)
            return    None
        f = open(filename, mode='rb')
        data = f.read()
        f.close()
        loader = gtk.gdk.PixbufLoader()
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


def add_close_accel(window, callback):
    if is_gtk3():
        return      #TODO: implement accel for gtk3
    accel_group = gtk.AccelGroup()
    accel_group.connect_group(ord('w'), gtk.gdk.CONTROL_MASK, gtk.ACCEL_LOCKED, callback)
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
    l.modify_fg(gtk.STATE_NORMAL, gtk.gdk.Color(red=48*256, green=0, blue=0))
    al = gtk.Alignment(xalign=0.0, yalign=0.5, xscale=0.0, yscale=0.0)
    al.set_padding(0, 0, 10, 10)
    al.add(l)
    eb.add(al)
    eb.modify_bg(gtk.STATE_NORMAL, gtk.gdk.Color(red=219*256, green=226*256, blue=242*256))
    return eb
