# This file is part of Xpra.
# Copyright (C) 2020 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.os_util import gi_import
from xpra.util.objects import AtomicInteger
from xpra.util.str_fn import csv, bytestostr
from xpra.util.env import IgnoreWarningsContext
from xpra.common import gravity_str, WORKSPACE_UNSET
from xpra.gtk.window import add_close_accel
from xpra.gtk.widget import label
from xpra.gtk.pixbuf import get_icon_pixbuf
from xpra.log import Logger

log = Logger("info")

Gtk = gi_import("Gtk")
Gdk = gi_import("Gdk")
GLib = gi_import("GLib")


def slabel(text: str = "", tooltip: str = "", font: str = "") -> Gtk.Label:
    lbl = label(text, tooltip, font)
    lbl.set_selectable(True)
    return lbl


def dict_str(d) -> str:
    return "\n".join("%s : %s" % (k, v) for k, v in d.items())


def geom_str(geom) -> str:
    return "%ix%i at %i,%i" % (geom[2], geom[3], geom[0], geom[1])


def hsc(sc) -> str:
    # make the dict more human-readable
    ssc = dict((bytestostr(k), v) for k, v in sc.items())
    ssc.pop("gravity", None)
    return dict_str(ssc)


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


class WindowInfo(Gtk.Window):

    def __init__(self, client, window):
        super().__init__()
        add_close_accel(self, self.close)
        self._client = client
        self._window = window
        self.is_closed = False
        self.set_title("Window Information for %s" % window.get_title())
        self.set_destroy_with_parent(True)
        self.set_resizable(True)
        self.set_decorated(True)
        self.set_transient_for(window)
        self.set_icon(get_icon_pixbuf("information.png"))
        self.set_position(Gtk.WindowPosition.CENTER_ON_PARENT)

        def window_deleted(*_args) -> None:
            self.is_closed = True

        self.connect('delete_event', window_deleted)

        grid = Gtk.Grid()
        grid.set_row_homogeneous(False)
        grid.set_column_homogeneous(False)
        row = AtomicInteger()

        def new_row(text="", widget=None) -> None:
            lbl = label(text)
            lbl.set_xalign(1)
            lbl.set_margin_end(10)
            grid.attach(lbl, 1, int(row), 1, 1)
            if widget:
                grid.attach(widget, 2, int(row), 1, 1)
            row.increase()

        def lrow(text: str) -> Gtk.Label:
            lbl = label()
            lbl.set_margin_start(10)
            lbl.set_xalign(0)
            lbl.set_line_wrap(True)
            new_row(text, lbl)
            return lbl

        def irow(text) -> Gtk.Image:
            image = Gtk.Image()
            image.set_margin_start(10)
            image.set_halign(Gtk.Align.START)
            image.set_hexpand(False)
            new_row(text, image)
            return image

        def sep() -> None:
            s = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
            s.set_margin_top(3)
            s.set_margin_bottom(3)
            grid.attach(s, 1, int(row), 2, 1)
            row.increase()

        self.wid_label = lrow("Window ID")
        self.title_label = lrow("Title")
        self.title_label.set_size_request(320, -1)
        self.rendering_label = lrow("Rendering")
        self.or_image = irow("Override-Redirect")
        self.state_label = lrow("State")
        self.attributes_label = lrow("Attributes")
        self.focus_image = irow("Focus")
        self.button_state_label = lrow("Button State")
        self.fps_label = lrow("Frames Per Second")
        sep()
        self.gravity_label = lrow("Gravity")
        self.content_type_label = lrow("Content Type")
        sep()
        self.pixel_depth_label = lrow("Pixel Depth")
        self.alpha_image = irow("Alpha Channel")
        self.opengl_image = irow("OpenGL")
        sep()
        self.geometry_label = lrow("Geometry")
        self.outer_geometry_label = lrow("Outer Geometry")
        self.inner_geometry_label = lrow("Inner Geometry")
        self.offsets_label = lrow("Offsets")
        self.frame_extents_label = lrow("Frame Extents")
        self.max_size_label = lrow("Maximum Size")
        self.size_constraints_label = lrow("Size Constraints")
        sep()
        # backing:
        self.video_properties = lrow("Video Decoder")
        sep()
        self.backing_properties = lrow("Backing Properties")
        sep()
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
        self.populate()
        self.set_size_request(320, -1)
        super().show_all()
        GLib.timeout_add(1000, self.populate)

    def populate(self) -> bool:
        if self.is_closed:
            return False
        self.do_populate()
        return True

    def copy_to_clipboard(self, *_args) -> None:
        w = self._window
        if not w:
            return
        info = {
            "wid": w.wid,
            "title": w.get_title(),
            "override-redirect": w._override_redirect,
            "state": get_window_state(w),
            "attributes": get_window_attributes(w),
            "focused": w._focused,
            "buttons": csv(b for b, s in w.button_pressed.items() if s) or "none",
            "gravity": gravity_str(w.window_gravity),
            "content-type": w.content_type or "unknown",
            "pixel-depth": w.pixel_depth or 24,
            "alpha": w._window_alpha,
            "opengl": w.is_GL(),
            "geometry": geom_str(list(w._pos) + list(w._size)),
            "outer-geometry": geom_str(list(w.get_position()) + list(w.get_size())),
            "inner-geometry": geom_str(w.get_drawing_area_geometry()),
            "offsets": csv(str(x) for x in (w.window_offset or ())) or "none",
            "frame-extents": csv(w._current_frame_extents or []) or "none",
            "max-size": csv(w.max_window_size),
            "size-constraints": hsc(w.size_constraints),
        }
        # backing:
        b = w._backing
        if b:
            info |= {
                "size": csv(b.size),
                "render-size": csv(b.render_size),
                "backing-offsets": csv(b.offsets),
            }
        text = "\n".join(f"{k}={v}" for k, v in info.items())
        clipboard = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)
        clipboard.set_text(text, len(text))

    def do_populate(self) -> None:
        w = self._window
        if not w:
            return
        fps = "n/a"
        b = w._backing
        binfo = {}
        if b:
            update_fps = getattr(b, "update_fps", None)
            if callable(update_fps):
                update_fps()
                fps = str(getattr(b, "fps_value", "n/a"))
            binfo = b.get_info()
        self.wid_label.set_text(str(w.wid))
        self.rendering_label.set_text(binfo.get("type", "unknown"))
        self.title_label.set_text(w.get_title())
        self.bool_icon(self.or_image, w._override_redirect)
        self.state_label.set_text(get_window_state(w))
        self.attributes_label.set_text(get_window_attributes(w))
        self.bool_icon(self.focus_image, w._focused)
        buttons = ()
        if hasattr(w, "button_pressed"):
            # this requires the PointerWindow subclass
            buttons = tuple(b for b, s in w.button_pressed.items() if s)
        self.button_state_label.set_text(csv(buttons) or "none")
        self.fps_label.set_text(fps)
        # self.group_leader_label.set_text(str(w.group_leader))
        self.gravity_label.set_text(gravity_str(w.window_gravity))
        self.content_type_label.set_text(w.content_type or "unknown")
        # geometry:
        self.pixel_depth_label.set_text(str(w.pixel_depth or 24))
        self.bool_icon(self.alpha_image, w._window_alpha)
        self.bool_icon(self.opengl_image, w.is_GL())
        # tells us if this window instance can paint with alpha
        geom = list(w._pos) + list(w._size)
        self.geometry_label.set_text(geom_str(geom))
        geom = list(w.get_position()) + list(w.get_size())
        self.outer_geometry_label.set_text(geom_str(geom))
        self.inner_geometry_label.set_text(geom_str(w.get_drawing_area_geometry()))
        self.offsets_label.set_text(csv(str(x) for x in (w.window_offset or ())) or "none")
        self.frame_extents_label.set_text(csv(w._current_frame_extents or []) or "none")
        self.max_size_label.set_text(csv(w.max_window_size))
        self.size_constraints_label.set_text(hsc(w.size_constraints))
        # backing:
        if b:
            self.backing_properties.show()

            def dict_to_str(d, sep="\n", eq="=", exclude=()) -> str:
                strdict = {k: pv(v) for k, v in d.items() if k not in exclude}
                return sep.join("%s%s%s" % (k, eq, v) for k, v in strdict.items() if v)

            def pv(value) -> str:
                if isinstance(value, (tuple, list)):
                    return csv(value)
                if isinstance(value, dict):
                    return dict_to_str(value, ", ", ":")
                return str(value)

            self.backing_properties.set_text(dict_to_str(binfo, exclude=(
                "transparency",
                "size",
                "render-size",
                "offsets",
                "fps",
                "mmap",
                "type",
                "bit-depth",
                "video-decoder",
            )))
            vdinfo = binfo.get("video-decoder")
            if vdinfo:
                self.video_properties.show()
                self.video_properties.set_text(dict_to_str(vdinfo))
            else:
                self.video_properties.hide()
        else:
            self.backing_properties.hide()
            self.backing_properties.set_text("")

    def bool_icon(self, image, on_off: bool) -> None:
        c = self._client
        if not c:
            return
        if on_off:
            icon = get_icon_pixbuf("ticked-small.png")
        else:
            icon = get_icon_pixbuf("unticked-small.png")
        image.set_from_pixbuf(icon)
