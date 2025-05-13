# -*- coding: utf-8 -*-
# This file is part of Xpra.
# Copyright (C) 2016-2023 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import socket
from typing import Optional, Tuple, Any
from gi.repository import GObject, Gdk, GLib  # @UnresolvedImport

from xpra.os_util import get_generic_os_name, load_binary_file
from xpra.platform.paths import get_icon, get_icon_filename
from xpra.gtk_common.gobject_util import one_arg_signal, no_arg_signal
from xpra.gtk_common.error import xsync
from xpra.x11.common import get_wm_name
from xpra.x11.models.model_stub import WindowModelStub
from xpra.x11.bindings.window import X11WindowBindings #@UnresolvedImport
from xpra.x11.gtk_x11.window_damage import WindowDamageHandler
from xpra.x11.gtk3.gdk_bindings import add_event_receiver, remove_event_receiver
from xpra.x11.bindings.randr import RandRBindings #@UnresolvedImport
from xpra.log import Logger

X11Window = X11WindowBindings()
RandR = RandRBindings()

eventlog = Logger("server", "window", "events")
geomlog = Logger("server", "window", "geometry")
iconlog = Logger("icon")


class DesktopModelBase(WindowModelStub, WindowDamageHandler):
    __common_gsignals__ = {}
    __common_gsignals__.update(WindowDamageHandler.__common_gsignals__)
    __common_gsignals__.update({
                         "resized"                  : no_arg_signal,
                         "client-contents-changed"  : one_arg_signal,
                         "motion"                   : one_arg_signal,
                         "xpra-motion-event"        : one_arg_signal,
                         "xpra-property-notify-event" : one_arg_signal,
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
        "title": (GObject.TYPE_PYOBJECT,
                       "The name of this desktop or monitor", "",
                       GObject.ParamFlags.READABLE),
        "icons": (GObject.TYPE_PYOBJECT,
                       "The icon of the window manager or session manager", "",
                       GObject.ParamFlags.READABLE),
        }

    _property_names = [
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
        WindowDamageHandler.__init__(self, root.get_xid())
        WindowModelStub.__init__(self)
        self.update_wm_name()
        self.update_icon()
        self._depth = 24
        self.resize_timer = 0
        self.resize_value = (1, 1)

    def setup(self) -> None:
        WindowDamageHandler.setup(self)
        self._depth = X11Window.get_depth(self.xid)
        X11Window.addDefaultEvents(self.xid)
        self._managed = True
        self._setup_done = True
        #listen for property changes on the root window:
        # (monitor mode can have up to 16 monitors, so we may have many event listeners
        #  so raise the limit to 20)
        add_event_receiver(self.xid, self, 20)

    def do_xpra_property_notify_event(self, event) -> None:
        eventlog(f"do_xpra_property_notify_event: {event.atom}")
        #update the wm-name (and therefore the window's "title")
        #whenever this property changes:
        if str(event.atom) == "_NET_SUPPORTING_WM_CHECK":
            if self.update_wm_name():
                self.update_icon()
                self.notify("title")

    def unmanage(self, exiting=False) -> None:
        remove_event_receiver(self.xid, self)
        WindowDamageHandler.destroy(self)
        WindowModelStub.unmanage(self, exiting)
        self.cancel_resize_timer()
        self._managed = False

    def update_wm_name(self) -> bool:
        try:
            with xsync:
                wm_name = get_wm_name()     #pylint: disable=assignment-from-none
        except Exception:
            wm_name = ""
        iconlog("update_wm_name() wm-name=%s", wm_name)
        return self._updateprop("wm-name", wm_name)

    def update_icon(self) -> bool:
        icons = None
        try:
            wm_name = self.get_property("wm-name")
            if not wm_name:
                return False
            icon_name = get_icon_filename(wm_name.lower()+".png")
            try:
                from PIL import Image  # pylint: disable=import-outside-toplevel
            except ImportError:
                iconlog("unable to get icon without pillow")
                img = None
            else:
                img = Image.open(icon_name)
                iconlog("Image(%s)=%s", icon_name, img)
            if img:
                icon_data = load_binary_file(icon_name)
                if not icon_data:
                    raise ValueError(f"failed to load icon {icon_name!r}")
                w, h = img.size
                icon = (w, h, "png", icon_data)
                icons = (icon,)
        except Exception:
            iconlog("failed to return window icon", exc_info=True)
        return self._updateprop("icons", icons)

    def uses_XShm(self) -> bool:
        return bool(self._xshm_handle)

    def get_default_window_icon(self, _size) -> Optional[Tuple[int,int,str,bytes]]:
        icon_name = get_generic_os_name()+".png"
        icon = get_icon(icon_name)
        if not icon:
            return None
        return icon.get_width(), icon.get_height(), "RGBA", icon.get_pixels()

    def get_title(self) -> str:
        return self.get_property("wm-name") or "xpra desktop"

    def get_property(self, prop:str) -> Any:
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

    def do_xpra_damage_event(self, event) -> None:
        self.emit("client-contents-changed", event)

    def do_xpra_motion_event(self, event) -> None:
        self.emit("motion", event)


    def resize(self, w:int, h:int):
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
            self.resize_timer = 0
            GLib.source_remove(rt)
