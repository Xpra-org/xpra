# This file is part of Xpra.
# Copyright (C) 2025 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from socket import gethostname

from xpra.util.gobject import one_arg_signal
from xpra.codecs.image import ImageWrapper
from xpra.server.window.model import WindowModelStub
from xpra.wayland.compositor import frame_done, flush_clients
from xpra.os_util import gi_import
from xpra.log import Logger

log = Logger("wayland", "window")

GObject = gi_import("GObject")


class Window(WindowModelStub):
    __gproperties__ = {
        "display": (
            GObject.TYPE_POINTER,
            "The wayland display pointer", "",
            GObject.ParamFlags.READABLE,
        ),
        "surface": (
            GObject.TYPE_POINTER,
            "The wayland surface pointer", "",
            GObject.ParamFlags.READABLE,
        ),
        "geometry": (
            GObject.TYPE_PYOBJECT,
            "current coordinates (x, y, w, h) for the window", "",
            GObject.ParamFlags.READABLE,
        ),
        "decorations": (
            GObject.TYPE_BOOLEAN,
            "Should the window be decorated?", "",
            False,
            GObject.ParamFlags.READABLE,
        ),
        "depth": (
            GObject.TYPE_INT,
            "window bit depth", "",
            -1, 64, -1,
            GObject.ParamFlags.READABLE,
        ),
        "has-alpha": (
            GObject.TYPE_BOOLEAN,
            "Does the window use transparency", "",
            False,
            GObject.ParamFlags.READABLE,
        ),
        "client-machine": (
            GObject.TYPE_PYOBJECT,
            "Host where client process is running", "",
            GObject.ParamFlags.READABLE,
        ),
        "pid": (
            GObject.TYPE_INT,
            "PID of owning process", "",
            -1, 65535, -1,
            GObject.ParamFlags.READABLE,
        ),
        "title": (
            GObject.TYPE_PYOBJECT,
            "Window title", "",
            GObject.ParamFlags.READABLE,
        ),
        "app-id": (
            GObject.TYPE_PYOBJECT,
            "Window app id", "",
            GObject.ParamFlags.READABLE,
        ),
        "role": (
            GObject.TYPE_PYOBJECT,
            "The window's role (ICCCM session management)", "",
            GObject.ParamFlags.READABLE,
        ),
        "command": (
            GObject.TYPE_PYOBJECT,
            "Command used to start or restart the client", "",
            GObject.ParamFlags.READABLE,
        ),
        "iconic": (
            GObject.TYPE_BOOLEAN,
            "ICCCM 'iconic' state -- any sort of 'not on desktop'.", "",
            True,
            GObject.ParamFlags.READWRITE,
        ),
        "maximized": (
            GObject.TYPE_BOOLEAN,
            "Is the window maximized", "",
            False,
            GObject.ParamFlags.READWRITE,
        ),
        "fullscreen": (
            GObject.TYPE_BOOLEAN,
            "Is the window maximized", "",
            False,
            GObject.ParamFlags.READWRITE,
        ),
        "image": (
            GObject.TYPE_PYOBJECT,
            "ImageWrapper of the surface pixels", "",
            GObject.ParamFlags.READABLE,
        ),
    }

    __gsignals__ = {
        # signals we emit:
        "unmanaged": one_arg_signal,
        "initiate-moveresize": one_arg_signal,
        "grab": one_arg_signal,
        "ungrab": one_arg_signal,
        "bell": one_arg_signal,
        "client-contents-changed": one_arg_signal,
        "motion": one_arg_signal,
    }

    # things that we expose:
    _property_names = [
        "depth", "has-alpha", "decorations",
        "client-machine", "pid",
        "title", "role", "app-id",
        "command",
        "iconic", "maximized", "fullscreen",
    ]
    # exposed and changing (should be watched for notify signals):
    _dynamic_property_names = [
        "title", "command",
        "iconic", "maximized", "fullscreen",
    ]
    # should not be exported to the clients:
    _internal_property_names = []
    _MODELTYPE = "Wayland"

    def __init__(self):
        super().__init__()
        self._internal_set_property("client-machine", gethostname())

    def __repr__(self) -> str:  # pylint: disable=arguments-differ
        surface = self._gproperties.get("surface", 0)
        return "WaylandWindow(%#x)" % surface

    def setup(self) -> None:
        self._managed = True
        self._setup_done = True

    def unmanage(self, exiting=False) -> None:
        if self._managed:
            self.emit("unmanaged", exiting)

    def do_unmanaged(self, wm_exiting: bool) -> None:
        if not self._managed:
            return
        self._managed = False
        self.managed_disconnect()

    def acknowledge_changes(self) -> None:
        if not self._managed:
            return
        surface = self._gproperties.get("surface", 0)
        if surface:
            frame_done(surface)
        display = self._gproperties.get("display", 0)
        if display:
            flush_clients(display)

    def get_image(self, x: int, y: int, width: int, height: int) -> ImageWrapper:
        image = self._gproperties["image"]
        w, h = self._gproperties["geometry"][2:4]
        if x >= w or y >= h:
            raise ValueError("invalid position %ix%i for window of size %ix%i" % (x, y, w, h))
        if x == 0 and y == 0 and width == w and height == h:
            return image
        iw = min(width, w - x)
        ih = min(height, h - y)
        return image.get_sub_image(x, y, iw, ih)

    def get_dimensions(self) -> tuple[int, int]:
        # just extracts the size from the geometry:
        return self._gproperties["geometry"][2:4]

    def get_geometry(self) -> tuple[int, int, int, int]:
        return self._gproperties["geometry"]

    ################################
    # Actions
    ################################

    def hide(self):
        pass

    def show(self):
        pass

    def raise_window(self) -> None:
        pass

    def set_active(self) -> None:
        pass

    def request_close(self) -> bool:
        pass
