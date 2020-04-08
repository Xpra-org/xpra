# -*- coding: utf-8 -*-
# This file is part of Xpra.
# Copyright (C) 2012-2020 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import socket

from xpra.util import prettify_plug_name
from xpra.os_util import (
    get_generic_os_name, do_get_generic_os_name,
    load_binary_file, get_linux_distribution,
    )
from xpra.platform.paths import get_icon_filename
from xpra.log import Logger

log = Logger("shadow")


class RootWindowModel:

    def __init__(self, root_window, capture=None):
        self.window = root_window
        self.geometry = root_window.get_geometry()[:4]
        self.capture = capture
        self.property_names = [
            "title", "class-instance",
            "client-machine", "window-type",
            "size-hints", "icons", "shadow",
            "depth",
            ]
        self.dynamic_property_names = []
        self.internal_property_names = ["content-type"]

    def __repr__(self):
        return "RootWindowModel(%s : %24s)" % (self.capture, self.geometry)

    def get_info(self) -> dict:
        info = {}
        c = self.capture
        if c:
            info["capture"] = c.get_info()
        return info

    def take_screenshot(self):
        return self.capture.take_screenshot()

    def get_image(self, x, y, width, height):
        ox, oy = self.geometry[:2]
        image = self.capture.get_image(ox+x, oy+y, width, height)
        if image and (ox>0 or oy>0):
            #adjust x and y of where the image is displayed on the client (target_x and target_y)
            #not where the image lives within the current buffer (x and y)
            image.set_target_x(x)
            image.set_target_y(y)
        return image

    def unmanage(self, exiting=False):
        pass

    def suspend(self):
        pass

    def is_managed(self):
        return True

    def is_tray(self):
        return False

    def is_OR(self):
        return False

    def has_alpha(self):
        return False

    def uses_XShm(self):
        return False

    def is_shadow(self):
        return True

    def get_default_window_icon(self, _size):
        return None

    def acknowledge_changes(self):
        pass

    def get_dimensions(self):
        #used by get_window_info only
        return self.geometry[2:4]

    def get_geometry(self):
        return self.geometry


    def get_property_names(self):
        return self.property_names

    def get_dynamic_property_names(self):
        return self.dynamic_property_names

    def get_internal_property_names(self):
        return self.internal_property_names

    def get_property(self, prop):
        #subclasses can define properties as attributes:
        attr_name = prop.replace("-", "_")
        if hasattr(self, attr_name):
            return getattr(self, attr_name)
        #otherwise fallback to default behaviour:
        if prop=="title":
            return prettify_plug_name(self.window.get_screen().get_display().get_name())
        if prop=="client-machine":
            return socket.gethostname()
        if prop=="window-type":
            return ["NORMAL"]
        if prop=="fullscreen":
            return False
        if prop=="shadow":
            return True
        if prop=="depth":
            return 24
        if prop=="scaling":
            return None
        if prop=="opacity":
            return None
        if prop=="size-hints":
            size = self.get_dimensions()
            return {
                "maximum-size"  : size,
                "minimum-size"  : size,
                "base-size" : size,
                }
        if prop=="class-instance":
            osn = do_get_generic_os_name()
            if osn=="Linux":
                try:
                    osn += "-"+get_linux_distribution()[0].replace(" ", "-")
                except Exception:
                    pass
            return ("xpra-%s" % osn.lower(), "Xpra %s" % osn.replace("-", " "))
        if prop=="icons":
            try:
                icon_name = get_icon_filename((get_generic_os_name() or "").lower()+".png")
                from PIL import Image
                img = Image.open(icon_name)
                log("Image(%s)=%s", icon_name, img)
                if img:
                    icon_data = load_binary_file(icon_name)
                    assert icon_data
                    w, h = img.size
                    icon = (w, h, "png", icon_data)
                    icons = (icon,)
                    return icons
            except Exception:   # pragma: no cover
                log("failed to return window icon")
                return ()
        if prop=="content-type":
            return "desktop"
        raise ValueError("invalid property: %s" % prop)

    def get(self, name, default_value=None):
        try:
            return self.get_property(name)
        except ValueError as e:
            log("get(%s, %s) %s on %s", name, default_value, e, self)
            return default_value


    def managed_connect(self, *args):   # pragma: no cover
        log.warn("ignoring managed signal connect request: %s", args)

    def connect(self, *args):           # pragma: no cover
        log.warn("ignoring signal connect request: %s", args)

    def disconnect(self, *args):        # pragma: no cover
        log.warn("ignoring signal disconnect request: %s", args)
