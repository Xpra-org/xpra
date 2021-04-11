# -*- coding: utf-8 -*-
# This file is part of Xpra.
# Copyright (C) 2011-2020 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from gi.repository import Gtk, GLib, GdkPixbuf

from xpra.util import envbool
from xpra.os_util import OSX
from xpra.gtk_common.gtk_util import menuitem
from xpra.gtk_common.about import about, close_about
from xpra.platform.gui import get_icon_size
from xpra.log import Logger

HIDE_DISABLED_MENU_ENTRIES = OSX

def make_min_auto_menu(title, min_options, options,
                       get_current_min_value,
                       get_current_value,
                       set_min_value_cb,
                       set_value_cb):
    #note: we must keep references to the parameters on the submenu
    #(closures and gtk callbacks don't mix so well!)
    submenu = Gtk.Menu()
    submenu.get_current_min_value = get_current_min_value
    submenu.get_current_value = get_current_value
    submenu.set_min_value_cb = set_min_value_cb
    submenu.set_value_cb = set_value_cb
    fstitle = Gtk.MenuItem()
    fstitle.set_label("Fixed %s:" % title)
    set_sensitive(fstitle, False)
    submenu.append(fstitle)
    submenu.menu_items = {}
    submenu.min_menu_items = {}
    def populate_menu(options, value, set_fn):
        found_match = False
        items = {}
        if value and value>0 and value not in options:
            options[value] = "%s%%" % value
        for s in sorted(options.keys()):
            t = options.get(s)
            qi = Gtk.CheckMenuItem(label=t)
            qi.set_draw_as_radio(True)
            candidate_match = s>=max(0, value)
            qi.set_active(not found_match and candidate_match)
            found_match |= candidate_match
            qi.connect('activate', set_fn, submenu)
            if s>0:
                qi.set_tooltip_text("%s%%" % s)
            submenu.append(qi)
            items[s] = qi
        return items
    def set_value(item, ss):
        if not item.get_active():
            return
        #user select a new value from the menu:
        s = -1
        for ts,tl in options.items():
            if tl==item.get_label():
                s = ts
                break
        if s>=0 and s!=ss.get_current_value():
            log("setting %s to %s", title, s)
            ss.set_value_cb(s)
            #deselect other items:
            for x in ss.menu_items.values():
                if x!=item:
                    x.set_active(False)
            #min is only relevant in auto-mode:
            if s!=0:
                for v,x in ss.min_menu_items.items():
                    x.set_active(v==0)
    submenu.menu_items.update(populate_menu(options, get_current_value(), set_value))
    submenu.append(Gtk.SeparatorMenuItem())
    mstitle = Gtk.MenuItem()
    mstitle.set_label("Minimum %s:" % title)
    set_sensitive(mstitle, False)
    submenu.append(mstitle)
    def set_min_value(item, ss):
        if not item.get_active():
            return
        #user selected a new min-value from the menu:
        s = -1
        for ts,tl in min_options.items():
            if tl==item.get_label():
                s = ts
                break
        if s>=0 and s!=ss.get_current_min_value():
            log("setting min-%s to %s", title, s)
            ss.set_min_value_cb(s)
            #deselect other min items:
            for x in ss.min_menu_items.values():
                if x!=item:
                    x.set_active(False)
            #min requires auto-mode:
            for x in ss.menu_items.values():
                if x.get_label()=="Auto":
                    if not x.get_active():
                        x.activate()
                else:
                    x.set_active(False)
    mv = -1
    if get_current_value()<=0:
        mv = get_current_min_value()
    submenu.min_menu_items.update(populate_menu(min_options, mv, set_min_value))
    submenu.show_all()
    return submenu

def make_encodingsmenu(get_current_encoding, set_encoding, encodings, server_encodings):
    encodings_submenu = Gtk.Menu()
    populate_encodingsmenu(encodings_submenu, get_current_encoding, set_encoding, encodings, server_encodings)
    return encodings_submenu

def populate_encodingsmenu(encodings_submenu, get_current_encoding, set_encoding, encodings, server_encodings):
    from xpra.codecs.loader import get_encoding_help, get_encoding_name
    encodings_submenu.get_current_encoding = get_current_encoding
    encodings_submenu.set_encoding = set_encoding
    encodings_submenu.encodings = encodings
    encodings_submenu.server_encodings = server_encodings
    encodings_submenu.index_to_encoding = {}
    encodings_submenu.encoding_to_index = {}
    NAME_TO_ENCODING = {}
    for i, encoding in enumerate(encodings):
        name = get_encoding_name(encoding)
        descr = get_encoding_help(encoding)
        NAME_TO_ENCODING[name] = encoding
        encoding_item = Gtk.CheckMenuItem(label=name)
        if descr:
            if encoding not in server_encodings:
                descr += "\n(not available on this server)"
            encoding_item.set_tooltip_text(descr)
        def encoding_changed(item):
            ensure_item_selected(encodings_submenu, item)
            enc = NAME_TO_ENCODING.get(item.get_label())
            log("encoding_changed(%s) enc=%s, current=%s", item, enc, encodings_submenu.get_current_encoding())
            if enc is not None and encodings_submenu.get_current_encoding()!=enc:
                encodings_submenu.set_encoding(enc)
        log("populate_encodingsmenu(..) encoding=%s, current=%s, active=%s",
            encoding, get_current_encoding(), encoding==get_current_encoding())
        encoding_item.set_active(encoding==get_current_encoding())
        sensitive = encoding in server_encodings
        if not sensitive and HIDE_DISABLED_MENU_ENTRIES:
            continue
        set_sensitive(encoding_item, encoding in server_encodings)
        encoding_item.set_draw_as_radio(True)
        encoding_item.connect("toggled", encoding_changed)
        encodings_submenu.append(encoding_item)
        encodings_submenu.index_to_encoding[i] = encoding
        encodings_submenu.encoding_to_index[encoding] = i
    encodings_submenu.show_all()
