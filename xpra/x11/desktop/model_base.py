# -*- coding: utf-8 -*-
# This file is part of Xpra.
# Copyright (C) 2016-2022 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import socket
from gi.repository import GObject, Gdk, GLib

from xpra.os_util import get_generic_os_name, load_binary_file
from xpra.platform.paths import get_icon, get_icon_filename
from xpra.platform.gui import get_wm_name
from xpra.gtk_common.gobject_util import one_arg_signal, no_arg_signal
from xpra.x11.models.model_stub import WindowModelStub
from xpra.x11.bindings.window_bindings import X11WindowBindings #@UnresolvedImport
from xpra.x11.gtk_x11.window_damage import WindowDamageHandler
from xpra.x11.bindings.randr_bindings import RandRBindings #@UnresolvedImport
from xpra.log import Logger

X11Window = X11WindowBindings()
RandR = RandRBindings()

geomlog = Logger("server", "window", "geometry")
iconlog = Logger("icon")


class DesktopModelBase(WindowModelStub, WindowDamageHandler):
    __common_gsignals__ = {}
    __common_gsignals__.update(WindowDamageHandler.__common_gsignals__)
    __common_gsignals__.update({
                         "resized"                  : no_arg_signal,
                         "client-contents-changed"  : one_arg_signal,
                         })

    __gproperties__ = {
        "iconic": (GObject.TYPE_BOOLEAN,
                   "ICCCM 'iconic' state -- any sort of 'not on desktop'.", "",
                   False,
                   GObject.ParamFlags.READWRITE),
        "focused": (GObject.TYPE_BOOLEAN,
                       "Is the window focused", "",
                       False,
                       GObject.ParamFlags.READWRITE),
        "size-hints": (GObject.TYPE_PYOBJECT,
                       "Client hints on constraining its size", "",
                       GObject.ParamFlags.READABLE),
        "wm-name": (GObject.TYPE_PYOBJECT,
                       "The name of the window manager or session manager", "",
                       GObject.ParamFlags.READABLE),
        "icons": (GObject.TYPE_PYOBJECT,
                       "The icon of the window manager or session manager", "",
                       GObject.ParamFlags.READABLE),
        }

    _property_names         = [
        "client-machine", "window-type",
        "shadow", "size-hints", "class-instance",
        "focused", "title", "depth", "icons",
        "content-type",
        "set-initial-position",
        ]
    _dynamic_property_names = ["size-hints", "title", "icons"]

    def __init__(self):
        screen = Gdk.Screen.get_default()
        root = screen.get_root_window()
        WindowDamageHandler.__init__(self, root)
        WindowModelStub.__init__(self)
        self.update_icon()
        self.resize_timer = None
        self.resize_value = None

    def setup(self):
        WindowDamageHandler.setup(self)
        self._depth = X11Window.get_depth(self.client_window.get_xid())
        self._managed = True
        self._setup_done = True

    def unmanage(self, exiting=False):
        WindowDamageHandler.destroy(self)
        WindowModelStub.unmanage(self, exiting)
        self.cancel_resize_timer()
        self._managed = False

    def update_wm_name(self):
        try:
            wm_name = get_wm_name()     #pylint: disable=assignment-from-none
        except Exception:
            wm_name = ""
        iconlog("update_wm_name() wm-name=%s", wm_name)
        return self._updateprop("wm-name", wm_name)

    def update_icon(self):
        icons = None
        try:
            wm_name = get_wm_name()     #pylint: disable=assignment-from-none
            if not wm_name:
                return
            icon_name = get_icon_filename(wm_name.lower()+".png")
            from PIL import Image
            img = Image.open(icon_name)
            iconlog("Image(%s)=%s", icon_name, img)
            if img:
                icon_data = load_binary_file(icon_name)
                assert icon_data
                w, h = img.size
                icon = (w, h, "png", icon_data)
                icons = (icon,)
        except Exception:
            iconlog("failed to return window icon", exc_info=True)
        self._updateprop("icons", icons)

    def uses_XShm(self):
        return bool(self._xshm_handle)

    def get_default_window_icon(self, _size):
        icon_name = get_generic_os_name()+".png"
        icon = get_icon(icon_name)
        if not icon:
            return None
        return icon.get_width(), icon.get_height(), "RGBA", icon.get_pixels()

    def get_title(self):
        return get_wm_name() or "xpra desktop"

    def get_property(self, prop):
        if prop=="depth":
            return self._depth
        if prop=="title":
            return self.get_title()
        if prop=="client-machine":
            return socket.gethostname()
        if prop=="window-type":
            return ["NORMAL"]
        if prop=="shadow":
            return True
        if prop=="class-instance":
            return ("xpra-desktop", "Xpra-Desktop")
        if prop=="content-type":
            return "desktop"
        if prop=="set-initial-position":
            return False
        return GObject.GObject.get_property(self, prop)

    def do_xpra_damage_event(self, event):
        self.emit("client-contents-changed", event)


    def resize(self, w, h):
        geomlog("resize(%i, %i)", w, h)
        if not RandR.has_randr():
            geomlog.error("Error: cannot honour resize request,")
            geomlog.error(" no RandR support on this display")
            return
        #FIXME: small race if the user resizes with randr,
        #at the same time as he resizes the window..
        self.resize_value = (w, h)
        if not self.resize_timer:
            self.resize_timer = GLib.timeout_add(250, self.do_resize)

    def do_resize(self):
        raise NotImplementedError

    def cancel_resize_timer(self):
        rt = self.resize_timer
        if rt:
            self.resize_timer = None
            GLib.source_remove(rt)
