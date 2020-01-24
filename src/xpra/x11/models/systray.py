# This file is part of Xpra.
# Copyright (C) 2008, 2009 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2011-2018 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from gi.repository import GObject

from xpra.x11.models.core import CoreX11WindowModel
from xpra.util import AdHocStruct
from xpra.log import Logger

log = Logger("x11", "window", "tray")


class SystemTrayWindowModel(CoreX11WindowModel):
    __gproperties__ = CoreX11WindowModel.__common_properties__.copy()
    __gproperties__.update({
        "tray": (GObject.TYPE_BOOLEAN,
                 "Is the window a system tray icon", "",
                 False,
                 GObject.ParamFlags.READABLE),
                })
    __gsignals__ = CoreX11WindowModel.__common_signals__.copy()
    _property_names = CoreX11WindowModel._property_names + ["tray"]
    _MODELTYPE = "Tray"

    def __init__(self, client_window):
        super().__init__(client_window)
        self._updateprop("tray", True)

    def __repr__(self):
        return "SystemTrayWindowModel(%#x)" % self.xid

    def _read_initial_X11_properties(self):
        self._internal_set_property("has-alpha", True)
        super()._read_initial_X11_properties()

    def move_resize(self, x : int, y : int, width : int, height : int):
        #Used by clients to tell us where the tray is located on screen
        log("SystemTrayModel.move_resize(%s, %s, %s, %s)", x, y, width, height)
        self.client_window.move_resize(x, y, width, height)
        self._updateprop("geometry", (x, y, width, height))
        #force a refresh:
        event = AdHocStruct()
        event.x = event.y = 0
        event.width , event.height = self.get_dimensions()
        self.emit("client-contents-changed", event)

GObject.type_register(SystemTrayWindowModel)
