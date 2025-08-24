# This file is part of Xpra.
# Copyright (C) 2011 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from collections.abc import Callable

from xpra.common import noop
from xpra.os_util import gi_import, OSX, WIN32
from xpra.util.env import IgnoreWarningsContext, ignorewarnings, envint
from xpra.log import Logger

Gtk = gi_import("Gtk")
Gdk = gi_import("Gdk")
Pango = gi_import("Pango")
GdkPixbuf = gi_import("GdkPixbuf")

log = Logger("gtk", "util")

FILE_CHOOSER_NATIVE = envint("XPRA_FILE_CHOOSER_NATIVE", int(OSX or WIN32))


def scaled_image(pixbuf, icon_size: int = 0) -> Gtk.Image | None:
    if not pixbuf:
        return None
    if icon_size:
        pixbuf = pixbuf.scale_simple(icon_size, icon_size, GdkPixbuf.InterpType.BILINEAR)
    return Gtk.Image.new_from_pixbuf(pixbuf)


def imagebutton(title, icon=None, tooltip="", clicked_callback: Callable | None = None, icon_size=32,
                default=False, min_size=None, label_color=None, label_font="") -> Gtk.Button:
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
        widget = button
        try:
            alignment = button.get_children()[0]
            b_hbox = alignment.get_children()[0]
            widget = b_hbox.get_children()[1]
        except (IndexError, AttributeError):
            pass
        if label_color:
            modify_fg(widget, label_color)
        if label_font:
            setfont(widget, label_font)
    return button


def modify_fg(widget, color, state=Gtk.StateType.NORMAL) -> None:
    with IgnoreWarningsContext():
        widget.modify_fg(state, color)


def menuitem(title, image=None, tooltip=None, cb=None) -> Gtk.ImageMenuItem:
    """ Utility method for easily creating an ImageMenuItem """
    menu_item = Gtk.ImageMenuItem()
    menu_item.set_label(title)
    if image:
        ignorewarnings(menu_item.set_image, image)
        # override gtk defaults: we *want* icons:
        settings = menu_item.get_settings()
        settings.set_property('gtk-menu-images', True)
        ignorewarnings(menu_item.set_always_show_image, True)
    if tooltip:
        menu_item.set_tooltip_text(tooltip)
    if cb:
        menu_item.connect('activate', cb)
    menu_item.show()
    return menu_item


def label(text="", tooltip="", font="") -> Gtk.Label:
    widget = Gtk.Label(label=text)
    if font:
        setfont(widget, font)
    if tooltip:
        widget.set_tooltip_text(tooltip)
    return widget


def setfont(widget, font=""):
    if font:
        with IgnoreWarningsContext():
            fontdesc = Pango.FontDescription(font)
            widget.modify_font(fontdesc)


def choose_files(parent_window, title, action=Gtk.FileChooserAction.OPEN, action_button=Gtk.STOCK_OPEN,
                 callback=None, file_filter=None, multiple=True) -> list[str]:
    log("choose_files%s", (parent_window, title, action, action_button, callback, file_filter))
    chooser = Gtk.FileChooserDialog(title=title, parent=parent_window, action=action)
    chooser.add_buttons(
        Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL,
        action_button, Gtk.ResponseType.OK,
    )
    chooser.set_select_multiple(multiple)
    chooser.set_default_response(Gtk.ResponseType.OK)
    if file_filter:
        chooser.add_filter(file_filter)
    response = chooser.run()
    filenames = chooser.get_filenames()
    chooser.hide()
    chooser.destroy()
    if response != Gtk.ResponseType.OK:
        return []
    return filenames


def choose_file(parent_window, title, action=Gtk.FileChooserAction.OPEN, action_button=Gtk.STOCK_OPEN,
                callback=noop, file_filter=None) -> None:
    filenames = choose_files(parent_window, title, action, action_button, callback, file_filter, False)
    if not filenames or len(filenames) != 1:
        return
    filename = filenames[0]
    callback(filename)


orig_pack_start = Gtk.Box.pack_start


def pack_start(self, child, expand=True, fill=True, padding=0) -> None:
    orig_pack_start(self, child, expand, fill, padding)


Gtk.Box.pack_start = pack_start


def slabel(text="", tooltip="", font="") -> Gtk.Label:
    lw = label(text, tooltip, font)
    lw.set_margin_start(5)
    lw.set_margin_end(5)
    lw.set_margin_top(2)
    lw.set_margin_bottom(2)
    lw.set_selectable(True)
    lw.set_line_wrap(True)
    return lw


def title_box(label_str: str, tooltip="") -> Gtk.EventBox:
    eb = Gtk.EventBox()
    lbl = slabel(label_str, tooltip=tooltip)
    modify_fg(lbl, Gdk.Color(red=48 * 256, green=0, blue=0))
    al = Gtk.Alignment(xalign=0.0, yalign=0.5, xscale=0.0, yscale=0.0)
    al.set_margin_start(10)
    al.set_margin_end(10)
    al.add(lbl)
    eb.add(al)
    with IgnoreWarningsContext():
        eb.modify_bg(Gtk.StateType.NORMAL, Gdk.Color(red=219 * 256, green=226 * 256, blue=242 * 256))
    return eb


def color_parse(*args) -> Gdk.Color | None:
    v = Gdk.RGBA()
    ok = v.parse(*args)
    if ok:
        return v.to_color()  # pylint: disable=no-member
    with IgnoreWarningsContext():
        ok, v = Gdk.Color.parse(*args)
    if ok:
        return v
    return None


black = color_parse("black")
red = color_parse("red")
white = color_parse("white")


def set_widget_bg_color(widget, is_error=False) -> None:
    with IgnoreWarningsContext():
        widget.modify_base(Gtk.StateType.NORMAL, red if is_error else white)


def set_widget_fg_color(widget, is_error=False) -> None:
    modify_fg(widget, red if is_error else black)


def checkitem(title, cb: Callable = noop, active=False) -> Gtk.CheckMenuItem:
    """ Utility method for easily creating a CheckMenuItem """
    check_item = Gtk.CheckMenuItem(label=title)
    check_item.set_active(active)
    if cb and cb != noop:
        check_item.connect("toggled", cb)
    check_item.show()
    return check_item
