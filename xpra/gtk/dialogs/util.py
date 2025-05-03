# This file is part of Xpra.
# Copyright (C) 2024 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from typing import Callable

from xpra.os_util import gi_import
from xpra.scripts.pinentry import log
from xpra.util.thread import is_main_thread

Gtk = gi_import("Gtk")
GLib = gi_import("GLib")
Gio = gi_import("Gio")


def do_run_dialog(dialog: Gtk.Dialog) -> int:
    from xpra.platform.gui import force_focus
    try:
        force_focus()
        dialog.show()
        return dialog.run()
    finally:
        dialog.hide()
        dialog.close()


def dialog_run(run_fn: Callable) -> str | int:
    log("dialog_run(%s) is_main_thread=%s, main_level=%i", run_fn, is_main_thread(), Gtk.main_level())
    if is_main_thread() or Gtk.main_level() == 0:
        return run_fn()
    log("dialog_run(%s) main_depth=%s", run_fn, GLib.main_depth())
    # do a little dance if we're not running in the main thread:
    # block this thread and wait for the main thread to run the dialog
    from threading import Event
    e = Event()
    code = []

    def main_thread_run() -> None:
        log("main_thread_run() calling %s", run_fn)
        try:
            code.append(run_fn())
        finally:
            e.set()

    GLib.idle_add(main_thread_run)
    log("dialog_run(%s) waiting for main thread to run", run_fn)
    e.wait()
    log("dialog_run(%s) code=%s", run_fn, code)
    return code[0]


ICON_SIZES: dict[int, int] = {}
for size_name in ("MENU", "SMALL_TOOLBAR", "LARGE_TOOLBAR", "BUTTON", "DND", "DIALOG"):
    value = getattr(Gtk.IconSize, size_name, -1)
    if value >= 0:
        valid, width, height = Gtk.IconSize.lookup(value)
        if valid:
            ICON_SIZES[max(width, height)] = value


def nearest_icon_size(size: int) -> int:
    # try to find a size smaller or equal:
    best = 0
    for icon_size in ICON_SIZES.keys():
        if best < icon_size <= size:
            best = icon_size
    return best


def nearest_icon_enum(size: int) -> Gtk.IconSize:
    # try to find a size smaller or equal:
    best_size = nearest_icon_size(size)
    return ICON_SIZES.get(best_size, Gtk.IconSize.MENU)


def load_hb_image(icon_name: str, size=32) -> Gtk.Image | None:
    from xpra.gtk.pixbuf import get_icon_pixbuf
    pixbuf = get_icon_pixbuf(f"{icon_name}.png")
    if pixbuf:
        if pixbuf.get_width() != size or pixbuf.get_height() != size:
            GdkPixbuf = gi_import("GdkPixbuf")
            pixbuf = pixbuf.scale_simple(size, size, GdkPixbuf.InterpType.HYPER)
        return Gtk.Image.new_from_pixbuf(pixbuf)
    # try from the theme:
    icon = Gio.ThemedIcon(name=icon_name)
    if not icon:
        return None
    icon_size = nearest_icon_enum(size)
    return Gtk.Image.new_from_gicon(icon, icon_size)


def hb_button(tooltip: str, icon_name: str, callback: Callable, size=32) -> Gtk.Button:
    btn = Gtk.Button()
    image = load_hb_image(icon_name, size)
    if image:
        btn.add(image)
        btn.set_tooltip_text(tooltip)
        current_size = [size, size]

        # keep image square:
        def alloc(_btn, rect) -> None:
            if current_size != [rect.width, rect.height]:
                new_size = max(rect.width, rect.height)
                btn.set_size_request(new_size, new_size)
                scaled_image = load_hb_image(icon_name, new_size)
                if image:
                    btn.set_image(scaled_image)
                    current_size[0] = current_size[1] = new_size

        image.connect("size-allocate", alloc)

    def clicked(*_args) -> None:
        callback(btn)

    btn.connect("clicked", clicked)
    return btn
