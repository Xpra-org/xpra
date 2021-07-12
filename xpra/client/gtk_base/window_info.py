# -*- coding: utf-8 -*-
# This file is part of Xpra.
# Copyright (C) 2020 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from gi.repository import Gtk, Gdk, GLib

from xpra.util import typedict, csv, WORKSPACE_UNSET
from xpra.os_util import bytestostr
from xpra.common import GRAVITY_STR
from xpra.gtk_common.gtk_util import (
    add_close_accel, label, TableBuilder,
    get_icon_pixbuf,
    )
from xpra.log import Logger

log = Logger("info")


def slabel(text="", tooltip=None, font=None):
    l = label(text, tooltip, font)
    l.set_selectable(True)
    return l


def x(self):
    self.size_constraints = typedict()
    self.geometry_hints = {}
    self.pending_refresh = []

def dict_str(d):
    return "\n".join("%s : %s" % (k,v) for k,v in d.items())

def geom_str(geom):
    return "%ix%i at %i,%i" % (geom[2], geom[3], geom[0], geom[1])

def hsc(sc):
    #make the dict more human readable
    ssc = dict((bytestostr(k),v) for k,v in sc.items())
    ssc.pop("gravity", None)
    return dict_str(ssc)

def get_window_state(w):
    state = []
    for s in (
        "fullscreen", "maximized",
        "above", "below", "shaded", "sticky",
        "skip-pager", "skip-taskbar",
        "iconified",
        ):
        #ie: "skip-pager" -> self.window._skip_pager
        if getattr(w, "_%s" % s.replace("-", "_"), False):
            state.append(s)
    for s in ("modal", ):
        fn = getattr(w, "get_%s" % s, None)
        if fn and fn():
            state.append(s)
    return csv(state) or "none"

def get_window_attributes(w):
    attr = {}
    workspace = w.get_desktop_workspace()
    if workspace not in (None, WORKSPACE_UNSET):
        attr["workspace"] = workspace
    opacity = w.get_opacity()
    if opacity<1:
        attr["opacity"] = opacity
    role = w.get_role()
    if role:
        attr["role"] = role
    #get_type_hint
    return dict_str(attr)


class WindowInfo(Gtk.Window):

    def __init__(self, client, window):
        Gtk.Window.__init__(self)
        add_close_accel(self, self.destroy)
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
        def window_deleted(*_args):
            self.is_closed = True
        self.connect('delete_event', window_deleted)

        tb = TableBuilder(1, 2)
        self.wid_label = slabel()
        tb.new_row("Window ID", self.wid_label)
        self.title_label = slabel()
        self.title_label.set_line_wrap(True)
        self.title_label.set_size_request(320, -1)
        #self.title_label.set_justify(Gtk.Justification.LEFT)
        self.title_label.set_alignment(0, 0.5)
        tb.new_row("Title", self.title_label)
        self.or_image = Gtk.Image()
        tb.new_row("Override-Redirect", self.or_image)
        self.state_label = slabel()
        tb.new_row("State", self.state_label)
        self.attributes_label = slabel()
        tb.new_row("Attributes", self.attributes_label)
        self.focus_image = Gtk.Image()
        tb.new_row("Focus", self.focus_image)
        self.button_state_label = slabel()
        tb.new_row("Button State", self.button_state_label)
        #self.group_leader_label = slabel()
        #tb.new_row("Group Leader", self.group_leader_label)
        tb.new_row("")
        self.gravity_label = slabel()
        tb.new_row("Gravity", self.gravity_label)
        self.content_type_label = slabel()
        tb.new_row("Content Type", self.content_type_label)
        tb.new_row("", slabel())
        self.pixel_depth_label = slabel()
        tb.new_row("Pixel Depth", self.pixel_depth_label)
        self.alpha_image = Gtk.Image()
        tb.new_row("Alpha Channel", self.alpha_image)
        self.opengl_image = Gtk.Image()
        tb.new_row("OpenGL", self.opengl_image)
        tb.new_row("")
        self.geometry_label = slabel()
        tb.new_row("Geometry", self.geometry_label)
        self.outer_geometry_label = slabel()
        tb.new_row("Outer Geometry", self.outer_geometry_label)
        self.inner_geometry_label = slabel()
        tb.new_row("Inner Geometry", self.inner_geometry_label)
        self.offsets_label = slabel()
        tb.new_row("Offsets", self.offsets_label)
        self.frame_extents_label = slabel()
        tb.new_row("Frame Extents", self.frame_extents_label)
        self.max_size_label = slabel()
        tb.new_row("Maximum Size", self.max_size_label)
        self.size_constraints_label = slabel()
        tb.new_row("Size Constraints", self.size_constraints_label)
        tb.new_row("")
        #backing:
        self.backing_properties = slabel()
        tb.new_row("Backing Properties", self.backing_properties)
        tb.new_row("")
        btn = Gtk.Button(label="Copy to clipboard")
        btn.connect("clicked", self.copy_to_clipboard)
        tb.new_row("", btn)
        vbox = Gtk.VBox()
        vbox.pack_start(tb.get_table(), True, True, 20)
        self.add(vbox)

    def destroy(self, *_args):
        self.is_closed = True
        Gtk.Window.destroy(self)

    def show(self):
        self.populate()
        self.set_size_request(320, -1)
        super().show_all()
        GLib.timeout_add(1000, self.populate)

    def populate(self):
        if self.is_closed:
            return False
        self.do_populate()
        return True

    def copy_to_clipboard(self, *_args):
        w = self._window
        if not w:
            return
        info = {
            "wid"               : w._id,
            "title"             : w.get_title(),
            "override-redirect" : w._override_redirect,
            "state"             : get_window_state(w),
            "attributes"        : get_window_attributes(w),
            "focused"           : w._focused,
            "buttons"           : csv(b for b,s in w.button_state.items() if s) or "none",
            "gravity"           : GRAVITY_STR.get(w.window_gravity, "invalid"),
            "content-type"      : w.content_type or "unknown",
            "pixel-depth"       : w.pixel_depth or 24,
            "alpha"             : w._window_alpha,
            "opengl"            : w.is_GL(),
            "geometry"          : geom_str(list(w._pos)+list(w._size)),
            "outer-geometry"    : geom_str(list(w.get_position()) + list(w.get_size())),
            "inner-geometry"    : geom_str(w.get_drawing_area_geometry()),
            "offsets"           : csv(str(x) for x in (w.window_offset or ())) or "none",
            "frame-extents"     : csv(w._current_frame_extents or []) or "none",
            "max-size"          : csv(w.max_window_size),
            "size-constraints"  : hsc(w.size_constraints),
            }
        #backing:
        b = w._backing
        if b:
            info.update({
                "size"              : csv(b.size),
                "render-size"       : csv(b.render_size),
                "backing-offsets"   : csv(b.offsets),
                })
        text = "\n".join("%s=%s" % (k,v) for k,v in info.items())
        clipboard = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)
        clipboard.set_text(text, len(text))

    def do_populate(self):
        w = self._window
        if not w:
            return
        self.wid_label.set_text(str(w._id))
        self.title_label.set_text(w.get_title())
        self.bool_icon(self.or_image, w._override_redirect)
        self.state_label.set_text(get_window_state(w))
        self.attributes_label.set_text(get_window_attributes(w))
        self.bool_icon(self.focus_image, w._focused)
        self.button_state_label.set_text(csv(b for b,s in w.button_state.items() if s) or "none")
        #self.group_leader_label.set_text(str(w.group_leader))
        self.gravity_label.set_text(GRAVITY_STR.get(w.window_gravity, "invalid"))
        self.content_type_label.set_text(w.content_type or "unknown")
        #geometry:
        self.pixel_depth_label.set_text(str(w.pixel_depth or 24))
        self.bool_icon(self.alpha_image, w._window_alpha)
        self.bool_icon(self.opengl_image, w.is_GL())
        #tells us if this window instance can paint with alpha
        geom = list(w._pos)+list(w._size)
        self.geometry_label.set_text(geom_str(geom))
        geom = list(w.get_position()) + list(w.get_size())
        self.outer_geometry_label.set_text(geom_str(geom))
        self.inner_geometry_label.set_text(geom_str(w.get_drawing_area_geometry()))
        self.offsets_label.set_text(csv(str(x) for x in (w.window_offset or ())) or "none")
        self.frame_extents_label.set_text(csv(w._current_frame_extents or []) or "none")
        self.max_size_label.set_text(csv(w.max_window_size))
        self.size_constraints_label.set_text(hsc(w.size_constraints))
        #backing:
        b = w._backing
        if b:
            self.backing_properties.show()
            def pv(value):
                if isinstance(value, (tuple, list)):
                    return csv(value)
                if isinstance(value, dict):
                    return dict_to_str(dict((k,v) for k,v in value.items() if k in ("type", "encoding", )), ", ", ":")
                return str(value)
            def dict_to_str(d, sep="\n", eq="="):
                strdict = dict((k,pv(v)) for k,v in d.items())
                return sep.join("%s%s%s" % (k, eq, v) for k,v in strdict.items() if v)
            self.backing_properties.set_text(dict_to_str(b.get_info()))
        else:
            self.backing_properties.hide()
            self.backing_properties.set_text("")


    def bool_icon(self, image, on_off):
        c = self._client
        if not c:
            return
        if on_off:
            icon = get_icon_pixbuf("ticked-small.png")
        else:
            icon = get_icon_pixbuf("unticked-small.png")
        image.set_from_pixbuf(icon)
