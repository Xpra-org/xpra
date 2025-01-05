# -*- coding: utf-8 -*-
# This file is part of Xpra.
# Copyright (C) 2016-2023 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from gi.repository import GObject, Gdk  # @UnresolvedImport

from xpra.gtk_common.error import XError, xsync
from xpra.x11.desktop.model_base import DesktopModelBase
from xpra.x11.bindings.randr import RandRBindings #@UnresolvedImport
from xpra.log import Logger

RandR = RandRBindings()

geomlog = Logger("server", "window", "geometry")
screenlog = Logger("screen")


class ScreenDesktopModel(DesktopModelBase):
    """
    A desktop model covering the entire screen as a single window.
    """
    __gsignals__ = dict(DesktopModelBase.__common_gsignals__)
    _property_names         = DesktopModelBase._property_names+["xid"]
    _dynamic_property_names = ["size-hints", "title", "icons"]

    def __init__(self, resize=True, resize_exact=False):
        super().__init__()
        self.screen = Gdk.Screen.get_default()
        self.can_resize = resize
        self.resize_exact = resize_exact

    def __repr__(self):
        return f"ScreenDesktopModel({self.xid:x})"


    def setup(self):
        super().setup()
        self.screen.connect("size-changed", self._screen_size_changed)
        self.update_size_hints()


    def get_geometry(self):
        return 0, 0, self.screen.get_width(), self.screen.get_height()

    def get_dimensions(self):
        return self.screen.get_width(), self.screen.get_height()


    def get_property(self, prop):
        if prop=="xid":
            return self.xid
        return super().get_property(prop)


    def do_resize(self):
        self.resize_timer = 0
        rw, rh = self.resize_value
        try:
            with xsync:
                ow, oh = RandR.get_screen_size()
            with xsync:
                if RandR.is_dummy16() and (rw, rh) not in RandR.get_screen_sizes():
                    RandR.add_screen_size(rw, rh)
            with xsync:
                if not RandR.set_screen_size(rw, rh):
                    geomlog.warn("Warning: failed to resize vfb")
                    return
            with xsync:
                w, h = RandR.get_screen_size()
            if (ow, oh) == (w, h):
                #this is already the resolution we have,
                #but the client has other ideas,
                #so tell the client we ain't budging:
                self.emit("resized")
        except Exception as e:
            geomlog("do_resize() %ix%i", rw, rh, exc_info=True)
            geomlog.error("Error: failed to resize desktop display to %ix%i:", rw, rh)
            geomlog.error(" %s", str(e) or type(e))

    def _screen_size_changed(self, screen):
        w, h = self.screen.get_width(), screen.get_height()
        screenlog("screen size changed: new size %ix%i", w, h)
        root = self.screen.get_root_window()
        screenlog("root window geometry=%s", root.get_geometry())
        self.invalidate_pixmap()
        self.update_size_hints()
        self.emit("resized")

    def update_size_hints(self):
        w, h = self.screen.get_width(), self.screen.get_height()
        screenlog("screen dimensions: %ix%i", w, h)
        size_hints = {}
        def use_fixed_size():
            size = w, h
            size_hints.update({
                "maximum-size": size,
                "minimum-size": size,
                "base-size": size,
            })

        if self.can_resize:
            if self.resize_exact:
                #assume resize_exact is enabled
                #no size restrictions
                size_hints = {}
            else:
                try:
                    with xsync:
                        screen_sizes = RandR.get_xrr_screen_sizes()
                except XError:
                    screenlog("failed to query screen sizes", exc_info=True)
                else:
                    if not screen_sizes:
                        use_fixed_size()
                    else:
                        #find the maximum size supported:
                        max_size = {}
                        for tw, th in screen_sizes:
                            max_size[tw*th] = (tw, th)
                        max_pixels = sorted(max_size.keys())[-1]
                        size_hints["maximum-size"] = max_size[max_pixels]
                        #find the best increment we can use:
                        inc_hits = {}
                        #we should also figure out what the potential increments are,
                        #rather than hardcoding them here:
                        INC_VALUES = (16, 32, 64, 128, 256)
                        for inc in INC_VALUES:
                            hits = 0
                            for tsize in screen_sizes:
                                tw, th = tsize
                                if (tw+inc, th+inc) in screen_sizes:
                                    hits += 1
                            inc_hits[inc] = hits
                        screenlog("size increment hits: %s", inc_hits)
                        max_hits = max(inc_hits.values())
                        if max_hits>16:
                            #find the first increment value matching the max hits
                            for inc in INC_VALUES:
                                if inc_hits[inc]==max_hits:
                                    break
                            #TODO: also get these values from the screen sizes:
                            size_hints.update({
                                "base-size"             : (640, 640),
                                "minimum-size"          : (640, 640),
                                "increment"             : (128, 128),
                                "minimum-aspect-ratio"  : (1, 3),
                                "maximum-aspect-ratio"  : (3, 1),
                                })
        else:
            use_fixed_size()
        screenlog("size-hints=%s", size_hints)
        self._updateprop("size-hints", size_hints)

GObject.type_register(ScreenDesktopModel)
