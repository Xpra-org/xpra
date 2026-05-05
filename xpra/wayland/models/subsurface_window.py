# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from typing import Any

from xpra.codecs.image import ImageWrapper
from xpra.os_util import gi_import
from xpra.server.window.model import WindowModelStub

GObject = gi_import("GObject")


class SubsurfaceWindow(WindowModelStub):
    """Minimal window-like facade so a WindowSource can be constructed for a
    wayland subsurface. The subsurface is not a window in its own right: it
    has no title, no parent/transient relationship the client cares about,
    and content-type is intentionally left unset so `content_guesser` decides
    from the pixel stream (a video subsurface should not inherit its parent
    GTK frame's "text" content-type)."""

    __gproperties__ = {
        "depth": (GObject.TYPE_INT, "bit depth", "", -1, 64, -1, GObject.ParamFlags.READABLE),
        "has-alpha": (GObject.TYPE_BOOLEAN, "alpha channel", "", False, GObject.ParamFlags.READABLE),
    }

    _property_names = ["depth", "has-alpha"]
    _dynamic_property_names: list[str] = []
    _internal_property_names: list[str] = []
    _MODELTYPE = "WaylandSubsurface"

    def __init__(self, width: int, height: int, has_alpha: bool = True, depth: int = 32):
        super().__init__()
        self._width = width
        self._height = height
        self._image: ImageWrapper | None = None
        self._internal_set_property("depth", depth)
        self._internal_set_property("has-alpha", has_alpha)
        self._setup_done = True
        self._managed = True

    def set_image(self, image: ImageWrapper) -> None:
        self._image = image
        self._width = image.get_width()
        self._height = image.get_height()

    def update_dimensions(self, width: int, height: int) -> None:
        self._width = width
        self._height = height

    def get_dimensions(self) -> tuple[int, int]:
        return self._width, self._height

    def get_geometry(self) -> tuple[int, int, int, int]:
        return 0, 0, self._width, self._height

    def get_image(self, x: int, y: int, width: int, height: int) -> ImageWrapper | None:
        image = self._image
        if image is None:
            return None
        if x == 0 and y == 0 and width == self._width and height == self._height:
            return image
        iw = min(width, self._width - x)
        ih = min(height, self._height - y)
        return image.get_sub_image(x, y, iw, ih)

    def get(self, name: str, default_value: Any = None) -> Any:
        if name == "content-type":
            return ""
        if name == "content-types":
            return ()
        if name == "opaque-region":
            return ()
        return super().get(name, default_value)

    def is_OR(self) -> bool:
        return False

    def is_tray(self) -> bool:
        return False

    def is_shadow(self) -> bool:
        return False
