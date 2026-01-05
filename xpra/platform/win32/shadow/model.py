# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.platform.win32.shadow.common import get_shape_rectangles
from xpra.server.shadow.root_window_model import CaptureWindowModel

from xpra.log import Logger

log = Logger("shadow")


class SeamlessCaptureWindowModel(CaptureWindowModel):

    def __init__(self, capture, title, geometry):
        super().__init__(capture, title, geometry)
        log("SeamlessCaptureWindowModel%s", (capture, title, geometry))
        self.property_names.append("shape")
        self.dynamic_property_names.append("shape")
        self.rectangles = get_shape_rectangles(logit=True)

    def refresh_shape(self) -> None:
        rectangles = get_shape_rectangles()
        if rectangles == self.rectangles:
            return  # unchanged
        self.rectangles = rectangles
        log("refresh_shape() sending notify for updated rectangles: %s", rectangles)
        self.notify("shape")

    def get_property(self, prop: str):
        if prop == "shape":
            shape = {"Bounding.rectangles": self.rectangles}
            # provide clip rectangle? (based on workspace area?)
            return shape
        return super().get_property(prop)


class Win32ShadowModel(CaptureWindowModel):
    __slots__ = ("hwnd", "iconic")

    def __init__(self, capture=None, title="", geometry=None):
        super().__init__(capture, title, geometry)
        self.hwnd = 0
        self.iconic = geometry[2] == -32000 and geometry[3] == -32000
        self.property_names.append("hwnd")
        self.dynamic_property_names.append("size-constraints")

    def get_id(self) -> int:
        return self.hwnd

    def __repr__(self):
        return "Win32ShadowModel(%s : %24s : %s)" % (self.capture, self.geometry, self.hwnd)
