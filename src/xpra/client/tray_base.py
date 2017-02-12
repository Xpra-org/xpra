# This file is part of Xpra.
# Copyright (C) 2010 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2011-2017 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.platform.paths import get_icon_filename
from xpra.log import Logger
from collections import deque
log = Logger("tray")


class TrayBase(object):
    """
        Utility superclass for all tray implementations
    """

    def __init__(self, client, app_id, menu, tooltip, icon_filename, size_changed_cb, click_cb, mouseover_cb, exit_cb):
        #we don't keep a reference to client,
        #because calling functions on the client directly should be discouraged
        self.app_id = app_id
        self.menu = menu
        self.tooltip = tooltip
        self.size_changed_cb = size_changed_cb
        self.click_cb = click_cb
        self.mouseover_cb = mouseover_cb
        self.exit_cb = exit_cb
        self.tray_widget = None
        self.default_icon_filename = icon_filename      #ie: "xpra" or "/path/to/xpra.png"
        #some implementations need this for guessing the geometry (see recalculate_geometry):
        self.geometry_guess = None
        self.tray_event_locations = deque(maxlen=512)
        self.default_icon_extension = "png"

    def cleanup(self):
        if self.tray_widget:
            self.hide()
            self.tray_widget = None

    def ready(self):
        pass

    def show(self):
        raise Exception("override me!")

    def hide(self):
        raise Exception("override me!")

    def get_screen(self):
        return -1

    def get_orientation(self):
        return None     #assume "HORIZONTAL"

    def get_geometry(self):
        raise Exception("override me!")

    def get_size(self):
        g = self.get_geometry()
        if g is None:
            return None
        return g[2:4]

    def set_tooltip(self, tooltip=None):
        self.tooltip = tooltip
        raise Exception("override me!")

    def set_blinking(self, on):
        raise Exception("override me!")


    def set_icon_from_data(self, pixels, has_alpha, w, h, rowstride, options={}):
        raise Exception("override me!")

    def get_icon_filename(self, basename=None):
        return get_icon_filename(basename or self.default_icon_filename, self.default_icon_extension)

    def set_icon(self, basename=None):
        filename = self.get_icon_filename(basename)
        if not filename:
            log.error("Error: cannot find icon '%s' for name '%s'", filename, basename)
            return
        log("set_icon(%s) using filename=%s", basename, filename)
        self.set_icon_from_file(filename)

    def set_icon_from_file(self, filename):
        log("set_icon_from_file(%s) tray_widget=%s", filename, self.tray_widget)
        if not self.tray_widget:
            return
        self.do_set_icon_from_file(filename)

    def do_set_icon_from_file(self, filename):
        raise Exception("override me!")

    def recalculate_geometry(self, x, y, width, height):
        log("recalculate_geometry%s tray event locations: %s", (x, y, width, height), len(self.tray_event_locations))
        if self.geometry_guess is None:
            #better than nothing!
            self.geometry_guess = x, y, width, height
        if len(self.tray_event_locations)>0 and self.tray_event_locations[-1]==(x,y):
            #unchanged
            return
        self.tray_event_locations.append((x, y))
        #sets of locations that can fit together within (size,size) distance of each other:
        xs, ys = set(), set()
        xs.add(x)
        ys.add(y)
        #walk though all of them in reverse (and stop when one does not fit):
        for tx, ty in reversed(self.tray_event_locations):
            minx = min(xs)
            miny = min(ys)
            maxx = max(xs)
            maxy = max(ys)
            if (tx<minx and tx<(maxx-width)) or (tx>maxx and tx>(minx+width)):
                break       #cannot fit...
            if (ty<miny and ty<(maxy-height)) or (ty>maxy and ty>(miny+height)):
                break       #cannot fit...
            xs.add(tx)
            ys.add(ty)
        #now add some padding if needed:
        minx = min(xs)
        miny = min(ys)
        maxx = max(xs)
        maxy = max(ys)
        padx = width-(maxx-minx)
        pady = height-(maxy-miny)
        assert padx>=0 and pady>=0
        minx -= padx//2
        miny -= pady//2
        oldgeom = self.geometry_guess
        self.geometry_guess = max(0, minx), max(0, miny), width, height
        log("recalculate_geometry() geometry guess=%s", self.geometry_guess)
        if self.size_changed_cb and self.geometry_guess!=oldgeom:
            self.size_changed_cb()
