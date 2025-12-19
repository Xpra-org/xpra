# This file is part of Xpra.
# Copyright (C) 2016 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import socket
from typing import Any

from xpra.common import BACKWARDS_COMPATIBLE
from xpra.os_util import gi_import
from xpra.util.system import get_generic_os_name
from xpra.util.io import load_binary_file
from xpra.platform.paths import get_icon, get_icon_filename
from xpra.util.gobject import no_arg_signal, one_arg_signal
from xpra.server.window.model import WindowModelStub
from xpra.x11.error import xlog
from xpra.x11.common import get_wm_name, X11Event
from xpra.x11.bindings.window import X11WindowBindings
from xpra.x11.damage import WindowDamageHandler
from xpra.x11.dispatch import add_event_receiver, remove_event_receiver
from xpra.x11.bindings.core import get_root_xid
from xpra.x11.bindings.randr import RandRBindings
from xpra.log import Logger

X11Window = X11WindowBindings()
RandR = RandRBindings()

eventlog = Logger("server", "window", "events")
geomlog = Logger("server", "window", "geometry")
iconlog = Logger("icon")

GObject = gi_import("GObject")
GLib = gi_import("GLib")


class DesktopModelBase(WindowModelStub, WindowDamageHandler):
    __common_gsignals__ = {}
    __common_gsignals__ |= WindowDamageHandler.__common_gsignals__
    __common_gsignals__ |= {
        "resized": no_arg_signal,
        "client-contents-changed": one_arg_signal,
        "motion": one_arg_signal,
        "x11-motion-event": one_arg_signal,
        "x11-property-notify-event": one_arg_signal,
        "x11-screen-change-event": one_arg_signal,
    }

    __gproperties__ = {
        "iconic": (
            GObject.TYPE_BOOLEAN,
            "ICCCM 'iconic' state -- any sort of 'not on desktop'.", "",
            False,
            GObject.ParamFlags.READWRITE,
        ),
        "focused": (
            GObject.TYPE_BOOLEAN,
            "Is the window focused", "",
            False,
            GObject.ParamFlags.READWRITE,
        ),
        "size-constraints": (
            GObject.TYPE_PYOBJECT,
            "Client hints on constraining its size", "",
            GObject.ParamFlags.READABLE,
        ),
        "wm-name": (
            GObject.TYPE_PYOBJECT,
            "The name of the window manager or session manager", "",
            GObject.ParamFlags.READABLE,
        ),
        "title": (
            GObject.TYPE_PYOBJECT,
            "The name of this desktop or monitor", "",
            GObject.ParamFlags.READABLE,
        ),
        "icons": (
            GObject.TYPE_PYOBJECT,
            "The icon of the window manager or session manager", "",
            GObject.ParamFlags.READABLE,
        ),
    }

    _property_names = [
        "client-machine", "window-type",
        "desktop", "size-constraints", "class-instance",
        "focused", "title", "depth", "icons",
        "content-type",
        "set-initial-position",
    ]
    if BACKWARDS_COMPATIBLE:
        _property_names.append("shadow")
    _dynamic_property_names = ["size-constraints", "title", "icons"]

    def __init__(self):
        root_xid = get_root_xid()
        WindowDamageHandler.__init__(self, root_xid)
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
        # listen for property changes on the root window:
        # (monitor mode can have up to 16 monitors, so we may have many event listeners
        #  so raise the limit to 20)
        add_event_receiver(self.xid, self, 20)

    def do_x11_property_notify_event(self, event: X11Event) -> None:
        eventlog(f"do_x11_property_notify_event: {event.atom}")
        # update the wm-name (and therefore the window's "title")
        # whenever this property changes:
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
        wm_name = ""
        with xlog:
            wm_name = get_wm_name()  # pylint: disable=assignment-from-none
        iconlog("update_wm_name() wm-name=%s", wm_name)
        return self._updateprop("wm-name", wm_name)

    def update_icon(self) -> bool:
        wm_name = self.get_property("wm-name")
        if not wm_name:
            return False
        icon_name = get_icon_filename(wm_name.lower() + ".png")
        if not icon_name:
            return False
        try:
            from xpra.codecs.pillow.decoder import open_only  # pylint: disable=import-outside-toplevel
        except ImportError:
            iconlog("unable to get icon without pillow")
            return False
        icon_data = load_binary_file(icon_name)
        if not icon_data:
            raise ValueError(f"failed to load icon {icon_name!r}")
        try:
            img = open_only(icon_data, types=("png",))
            w, h = img.size
            img.close()
        except OSError:
            iconlog("failed to open window icon", exc_info=True)
            return False
        iconlog("Image(%s)=%s", icon_name, img)
        if not img:
            return False
        icon = (w, h, "png", icon_data)
        icons = (icon,)
        return self._updateprop("icons", icons)

    def uses_xshm(self) -> bool:
        return bool(self._xshm_handle)

    def get_default_window_icon(self, _size: int = 48) -> tuple[int, int, str, bytes] | None:
        icon_name = get_generic_os_name() + ".png"
        icon = get_icon(icon_name)
        if not icon:
            return None
        return icon.get_width(), icon.get_height(), "RGBA", icon.get_pixels()

    def get_title(self) -> str:
        return self.get_property("wm-name") or "xpra desktop"

    def get_property(self, prop: str) -> Any:
        if prop == "depth":
            return self._depth
        if prop == "title":
            return self.get_title()
        if prop == "client-machine":
            return socket.gethostname()
        if prop == "window-type":
            return ["NORMAL"]
        if prop == "shadow" and BACKWARDS_COMPATIBLE:
            return True
        if prop == "desktop":
            return True
        if prop == "class-instance":
            return "xpra-desktop", "Xpra-Desktop"
        if prop == "content-type":
            return "desktop"
        if prop == "set-initial-position":
            return False
        return GObject.GObject.get_property(self, prop)

    def do_x11_damage_event(self, event: X11Event) -> None:
        self.emit("client-contents-changed", event)

    def do_x11_motion_event(self, event: X11Event) -> None:
        self.emit("motion", event)

    def resize(self, w: int, h: int) -> None:
        geomlog("resize(%i, %i)", w, h)
        if not RandR.has_randr():
            geomlog.error("Error: cannot honour resize request,")
            geomlog.error(" no RandR support on this display")
            return
        # FIXME: small race if the user resizes with randr,
        # at the same time as he resizes the window..
        self.resize_value = (w, h)
        if not self.resize_timer:
            self.resize_timer = GLib.timeout_add(250, self.do_resize)

    def do_resize(self) -> None:
        raise NotImplementedError

    def cancel_resize_timer(self) -> None:
        rt = self.resize_timer
        if rt:
            self.resize_timer = 0
            GLib.source_remove(rt)
