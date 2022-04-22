# -*- coding: utf-8 -*-
# This file is part of Xpra.
# Copyright (C) 2022 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from collections import namedtuple
from gi.repository import GObject

from xpra.platform.gui import get_wm_name
from xpra.x11.desktop.model_base import DesktopModelBase
from xpra.rectangle import rectangle  #@UnresolvedImport
from xpra.log import Logger

log = Logger("server")


MIN_SIZE = 640, 350
MAX_SIZE = 8192, 8192

MonitorDamageNotify = namedtuple("MonitorDamageNotify", "x,y,width,height")


class MonitorDesktopModel(DesktopModelBase):
    """
    A desktop model representing a single monitor
    """
    __gsignals__ = dict(DesktopModelBase.__common_gsignals__)

    #bump the number of receivers,
    #because we add all the monitor models as receivers for the root window:
    MAX_RECEIVERS = 20

    def __repr__(self):
        return "MonitorDesktopModel(%s : %s)" % (self.name, self.monitor_geometry)

    def __init__(self, monitor):
        super().__init__()
        self.init(monitor)

    def init(self, monitor):
        self.name = monitor.get("name", "")
        self.resize_delta = 0, 0
        x = monitor.get("x", 0)
        y = monitor.get("y", 0)
        width = monitor.get("width", 0)
        height = monitor.get("height", 0)
        self.monitor_geometry = (x, y, width, height)
        self._updateprop("size-hints", {
            "minimum-size"          : MIN_SIZE,
            "maximum-size"          : MAX_SIZE,
            })

    def get_title(self):
        title = get_wm_name()  # pylint: disable=assignment-from-none
        if self.name:
            if not title:
                return self.name
            title += " on %s" % self.name
        return title

    def get_geometry(self):
        return self.monitor_geometry

    def get_dimensions(self):
        return self.monitor_geometry[2:4]


    def get_definition(self):
        x, y, width, height = self.monitor_geometry
        return {
            "x"         : x,
            "y"         : y,
            "width"     : width,
            "height"    : height,
            "name"      : self.name,
            }


    def do_xpra_damage_event(self, event):
        #ie: <X11:DamageNotify {'send_event': '0', 'serial': '0x4da', 'delivered_to': '0x56e', 'window': '0x56e',
        #                       'damage': '2097157', 'x': '313', 'y': '174', 'width': '6', 'height': '13'}>)
        damaged_area = rectangle(event.x, event.y, event.width, event.height)
        x, y, width, height = self.monitor_geometry
        monitor_damaged_area = damaged_area.intersection(x, y, width, height)
        if monitor_damaged_area:
            #use an event relative to this monitor's coordinates:
            mod_event = MonitorDamageNotify(monitor_damaged_area.x-x, monitor_damaged_area.y-y,
                                            monitor_damaged_area.width, monitor_damaged_area.height)
            self.emit("client-contents-changed", mod_event)

    def get_image(self, x, y, width, height):
        #adjust the coordinates with the monitor's position:
        mx, my = self.monitor_geometry[:2]
        image = super().get_image(mx+x, my+y, width, height)
        if image:
            image.set_target_x(x)
            image.set_target_y(y)
        return image


    def do_resize(self):
        self.resize_timer = None
        x, y, saved_width, saved_height = self.monitor_geometry
        width, height = self.resize_value
        self.monitor_geometry = (x, y, width, height)
        self.resize_delta = width-saved_width, height-saved_height
        self.emit("resized")


GObject.type_register(MonitorDesktopModel)
