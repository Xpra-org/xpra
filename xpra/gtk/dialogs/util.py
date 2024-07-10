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

    def main_thread_run():
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


def nearest_icon_size(size: int) -> Gtk.IconSize:
    # try to find a size smaller or equal:
    best = Gtk.IconSize.MENU
    for icon_size, enum_value in ICON_SIZES.items():
        if icon_size <= size:
            best = enum_value
    return best


def load_hb_icon(icon_name: str, size=32):
    from xpra.gtk.pixbuf import get_icon_pixbuf
    pixbuf = get_icon_pixbuf(f"{icon_name}.png")
    if pixbuf:
        GdkPixbuf = gi_import("GdkPixbuf")
        return pixbuf.scale_simple(size, size, GdkPixbuf.InterpType.HYPER)
    theme = Gtk.IconTheme.get_default()
    icon_size = nearest_icon_size(size)
    try:
        pixbuf = theme.load_icon(icon_name, icon_size, Gtk.IconLookupFlags.USE_BUILTIN)
    except Exception:
        pixbuf = None
    return pixbuf


def hb_button(tooltip: str, icon_name: str, callback: Callable) -> Gtk.Button:
    btn = Gtk.Button()
    pixbuf = load_hb_icon(icon_name)
    if pixbuf:
        image = Gtk.Image.new_from_pixbuf(pixbuf)
        btn.add(image)
        btn.set_tooltip_text(tooltip)
        current_size = [pixbuf.get_width(), pixbuf.get_height()]

    # keep image square:
        def alloc(_btn, rect) -> None:
            log.warn(f"alloc: {current_size=}, [{rect.width}, {rect.height}]")
            if current_size != [rect.width, rect.height]:
                size = max(rect.width, rect.height)
                btn.set_size_request(size, size)
                scaled = load_hb_icon(icon_name, size)
                scaled_image = Gtk.Image.new_from_pixbuf(scaled)
                btn.set_image(scaled_image)
                current_size[0] = current_size[1] = size

        image.connect("size-allocate", alloc)

    def clicked(*_args) -> None:
        callback(btn)

    btn.connect("clicked", clicked)
    return btn
