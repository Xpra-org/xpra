# This file is part of Xpra.
# Copyright (C) 2020 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from typing import Any

from xpra.os_util import gi_import
from xpra.util.objects import AtomicInteger
from xpra.util.str_fn import csv
from xpra.util.env import IgnoreWarningsContext
from xpra.common import gravity_str
from xpra.constants import WORKSPACE_UNSET
from xpra.client.gui.window.info import (
    WINDOW_INFO_ROWS, dict_str, geom_str, hsc, get_backing_info, window_info_text,
)
from xpra.gtk.window import add_close_accel
from xpra.gtk.widget import label
from xpra.gtk.pixbuf import get_icon_pixbuf
from xpra.log import Logger

log = Logger("info")

Gtk = gi_import("Gtk")
Gdk = gi_import("Gdk")
GLib = gi_import("GLib")

# these rows are shown as a ticked / unticked icon:
BOOL_ROWS = ("override-redirect", "focused", "alpha", "opengl")


def slabel(text: str = "", tooltip: str = "", font: str = "") -> Gtk.Label:
    lbl = label(text, tooltip, font)
    lbl.set_selectable(True)
    return lbl


def get_window_state(w) -> str:
    state = []
    for s in (
            "fullscreen", "maximized",
            "above", "below", "shaded", "sticky",
            "skip-pager", "skip-taskbar",
            "iconified",
    ):
        # ie: "skip-pager" -> self.window._skip_pager
        if getattr(w, "_%s" % s.replace("-", "_"), False):
            state.append(s)
    for s in ("modal",):
        fn = getattr(w, "get_%s" % s, None)
        # noinspection calling-non-callable
        if fn and fn():
            state.append(s)
    return csv(state) or "none"


def get_window_attributes(w) -> str:
    attr = {}
    # optional feature:
    info: dict = w.get_info()
    workspace = info.get("workspace")
    if workspace not in (None, WORKSPACE_UNSET):
        attr["workspace"] = workspace
    with IgnoreWarningsContext():
        opacity = w.get_opacity()
    if opacity < 1:
        attr["opacity"] = opacity
    role = w.get_role()
    if role:
        attr["role"] = role
    # get_type_hint
    return dict_str(attr)


def get_gtk_window_info(w) -> dict[str, Any]:
    """
    The window information dictionary for a GTK client window
    """
    buttons = ()
    if hasattr(w, "button_pressed"):
        # this requires the PointerWindow subclass
        buttons = tuple(b for b, s in w.button_pressed.items() if s)
    info: dict[str, Any] = {
        "wid": str(w.wid),
        "title": w.get_title(),
        "override-redirect": bool(w._override_redirect),
        "state": get_window_state(w),
        "attributes": get_window_attributes(w),
        "focused": bool(w._focused),
        "buttons": csv(buttons) or "none",
        "gravity": gravity_str(w.window_gravity),
        "content-types": csv(w.content_types) or "unknown",
        "pixel-depth": str(w.pixel_depth or 24),
        # tells us if this window instance can paint with alpha:
        "alpha": bool(w._window_alpha),
        "opengl": bool(w.is_GL()),
        "geometry": geom_str(list(w._pos) + list(w._size)),
        "outer-geometry": geom_str(list(w.get_position()) + list(w.get_size())),
        "inner-geometry": geom_str(w.get_drawing_area_geometry()),
        "offsets": csv(str(x) for x in (w.window_offset or ())) or "none",
        "frame-extents": csv(w._current_frame_extents or []) or "none",
        "max-size": csv(w.max_window_size),
        "size-constraints": hsc(w.size_constraints),
    }
    info.update(get_backing_info(w._backing))
    return info


class WindowInfo(Gtk.Window):
    """
    Shows the dictionary returned by the window's `get_window_info()` method,
    which may or may not be a GTK window.
    """

    def __init__(self, window):
        super().__init__()
        add_close_accel(self, self.close)
        self._window = window
        self.is_closed = False
        info = window.get_window_info()
        self.set_title("Window Information for %s" % info.get("title", ""))
        self.set_resizable(True)
        self.set_decorated(True)
        if isinstance(window, Gtk.Window):
            self.set_destroy_with_parent(True)
            self.set_transient_for(window)
            self.set_position(Gtk.WindowPosition.CENTER_ON_PARENT)
        else:
            self.set_position(Gtk.WindowPosition.CENTER)
        self.set_icon(get_icon_pixbuf("information.png"))

        def window_deleted(*_args) -> None:
            self.is_closed = True

        self.connect('delete_event', window_deleted)

        grid = Gtk.Grid()
        grid.set_row_homogeneous(False)
        grid.set_column_homogeneous(False)
        row = AtomicInteger()
        # for each key: the label and the value widget
        self.rows: dict[str, tuple[Gtk.Label, Gtk.Label | Gtk.Image]] = {}
        # the keys and separators, in order:
        self.layout: list[str | Gtk.Separator] = []

        def new_row(key: str, text: str) -> None:
            lbl = label(text)
            lbl.set_xalign(1)
            lbl.set_margin_end(10)
            lbl.set_no_show_all(True)
            grid.attach(lbl, 1, int(row), 1, 1)
            if key in BOOL_ROWS:
                widget = Gtk.Image()
                widget.set_halign(Gtk.Align.START)
                widget.set_hexpand(False)
            else:
                widget = label()
                widget.set_xalign(0)
                widget.set_line_wrap(True)
            widget.set_margin_start(10)
            widget.set_no_show_all(True)
            grid.attach(widget, 2, int(row), 1, 1)
            self.rows[key] = (lbl, widget)
            self.layout.append(key)
            row.increase()

        def sep() -> None:
            s = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
            s.set_margin_top(3)
            s.set_margin_bottom(3)
            s.set_no_show_all(True)
            grid.attach(s, 1, int(row), 2, 1)
            self.layout.append(s)
            row.increase()

        for entry in WINDOW_INFO_ROWS:
            if entry is None:
                sep()
            else:
                new_row(*entry)
        self.rows["title"][1].set_size_request(320, -1)
        btn = Gtk.Button(label="Copy to clipboard")
        btn.connect("clicked", self.copy_to_clipboard)
        grid.attach(btn, 1, int(row), 2, 1)
        vbox = Gtk.VBox()
        vbox.pack_start(grid, True, True, 20)
        self.add(vbox)

    def close(self, *_args) -> None:
        self.is_closed = True
        self.hide()
        super().close()

    def show(self) -> None:
        self.set_size_request(320, -1)
        # the rows are excluded from `show_all()`, `populate()` shows the ones we have:
        self.populate()
        super().show_all()
        GLib.timeout_add(1000, self.populate)

    def populate(self) -> bool:
        if self.is_closed:
            return False
        self.do_populate()
        return True

    def get_window_info(self) -> dict[str, Any]:
        w = self._window
        if not w:
            return {}
        return w.get_window_info()

    def copy_to_clipboard(self, *_args) -> None:
        text = window_info_text(self.get_window_info())
        clipboard = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)
        clipboard.set_text(text, len(text))

    def do_populate(self) -> None:
        info = self.get_window_info()
        if not info:
            return
        for key, (lbl, widget) in self.rows.items():
            value = info.get(key)
            # hide the rows this window type does not provide:
            visible = value is not None and value != ""
            lbl.set_visible(visible)
            widget.set_visible(visible)
            if not visible:
                continue
            if key in BOOL_ROWS:
                self.bool_icon(widget, bool(value))
            else:
                widget.set_text(str(value))
        self.update_separators()

    def update_separators(self) -> None:
        # only show a separator between two groups that have visible rows:
        pending = None
        rows_above = False
        for item in self.layout:
            if isinstance(item, Gtk.Separator):
                item.hide()
                if rows_above:
                    pending = item
            elif self.rows[item][0].get_visible():
                if pending:
                    pending.show()
                    pending = None
                rows_above = True

    def bool_icon(self, image, on_off: bool) -> None:
        if on_off:
            icon = get_icon_pixbuf("ticked-small.png")
        else:
            icon = get_icon_pixbuf("unticked-small.png")
        image.set_from_pixbuf(icon)
