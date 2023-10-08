# This file is part of Xpra.
# Copyright (C) 2011-2023 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import warnings
from typing import Callable, Any
from contextlib import AbstractContextManager

import gi
gi.require_version("Gtk", "3.0")  # @UndefinedVariable
gi.require_version("Pango", "1.0")  # @UndefinedVariable
from gi.repository import Gtk, Pango     #@UnresolvedImport

from xpra.log import Logger
log = Logger("gtk", "util")


def scaled_image(pixbuf, icon_size:int=0) -> Gtk.Image | None:
    if not pixbuf:
        return None
    if icon_size:
        gi.require_version("GdkPixbuf", "2.0")  # @UndefinedVariable
        from gi.repository import GdkPixbuf
        pixbuf = pixbuf.scale_simple(icon_size, icon_size, GdkPixbuf.InterpType.BILINEAR)
    return Gtk.Image.new_from_pixbuf(pixbuf)


def imagebutton(title, icon=None, tooltip="", clicked_callback:Callable|None=None, icon_size=32,
                default=False, min_size=None, label_color=None, label_font:str="") -> Gtk.Button:
    button = Gtk.Button(label=title)
    settings = button.get_settings()
    settings.set_property('gtk-button-images', True)
    if icon:
        if icon_size:
            icon = scaled_image(icon, icon_size)
        ignorewarnings(button.set_image, icon)
    if tooltip:
        button.set_tooltip_text(tooltip)
    if min_size:
        button.set_size_request(min_size, min_size)
    if clicked_callback:
        button.connect("clicked", clicked_callback)
    if default:
        button.set_can_default(True)
    if label_color or label_font:
        l = button
        try:
            alignment = button.get_children()[0]
            b_hbox = alignment.get_children()[0]
            l = b_hbox.get_children()[1]
        except (IndexError, AttributeError):
            pass
        if label_color:
            modify_fg(l, label_color)
        if label_font:
            setfont(l, label_font)
    return button

def modify_fg(widget, color, state=Gtk.StateType.NORMAL):
    if hasattr(widget, "modify_fg"):
        with IgnoreWarningsContext():
            widget.modify_fg(state, color)


def menuitem(title, image=None, tooltip=None, cb=None) -> Gtk.ImageMenuItem:
    """ Utility method for easily creating an ImageMenuItem """
    menu_item = Gtk.ImageMenuItem()
    menu_item.set_label(title)
    if image:
        ignorewarnings(menu_item.set_image, image)
        #override gtk defaults: we *want* icons:
        settings = menu_item.get_settings()
        settings.set_property('gtk-menu-images', True)
        if hasattr(menu_item, "set_always_show_image"):
            ignorewarnings(menu_item.set_always_show_image, True)
    if tooltip:
        menu_item.set_tooltip_text(tooltip)
    if cb:
        menu_item.connect('activate', cb)
    menu_item.show()
    return menu_item


def label(text:str="", tooltip:str="", font:str="") -> Gtk.Label:
    l = Gtk.Label(label=text)
    if font:
        setfont(l, font)
    if tooltip:
        l.set_tooltip_text(tooltip)
    return l


def setfont(widget, font=""):
    if font:
        with IgnoreWarningsContext():
            fontdesc = Pango.FontDescription(font)
            widget.modify_font(fontdesc)


class IgnoreWarningsContext(AbstractContextManager):

    def __enter__(self):
        warnings.filterwarnings("ignore", category=DeprecationWarning)

    def __exit__(self, exc_type, exc_val, exc_tb):
        warnings.filterwarnings("default")

    def __repr__(self):
        return "IgnoreWarningsContext"

def ignorewarnings(fn, *args) -> Any:
    import warnings
    try:
        warnings.filterwarnings("ignore", category=DeprecationWarning)
        return fn(*args)
    finally:
        warnings.filterwarnings("default")


def choose_files(parent_window, title, action=Gtk.FileChooserAction.OPEN, action_button=Gtk.STOCK_OPEN,
                 callback=None, file_filter=None, multiple=True):
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


def choose_file(parent_window, title, action=Gtk.FileChooserAction.OPEN, action_button=Gtk.STOCK_OPEN,
                callback=None, file_filter=None):
    filenames = choose_files(parent_window, title, action, action_button, callback, file_filter, False)
    if not filenames or len(filenames)!=1:
        return
    filename = filenames[0]
    if callback:
        callback(filename)


orig_pack_start = Gtk.Box.pack_start


def pack_start(self, child, expand=True, fill=True, padding=0):
    orig_pack_start(self, child, expand, fill, padding)
Gtk.Box.pack_start = pack_start