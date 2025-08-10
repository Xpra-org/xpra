# This file is part of Xpra.
# Copyright (C) 2012 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import socket
from typing import Any
from collections import namedtuple
from collections.abc import Sequence

from xpra.util.system import get_linux_distribution, get_generic_os_name
from xpra.util.io import load_binary_file
from xpra.platform.paths import get_icon_filename
from xpra.log import Logger

log = Logger("shadow")


def get_os_icons() -> Sequence[tuple[int, int, str, bytes]]:
    try:
        from PIL import Image  # pylint: disable=import-outside-toplevel
    except ImportError:
        return ()
    filename = (get_generic_os_name() or "").lower() + ".png"
    icon_name = get_icon_filename(filename)
    if not icon_name:
        log(f"get_os_icons() no icon matching {filename!r}")
        return ()
    with log.trap_error(f"Error: failed to load window icon {icon_name!r}"):
        img = Image.open(icon_name)
        log(f"Image({icon_name})={img}")
        if img:
            icon_data = load_binary_file(icon_name)
            if not icon_data:
                log(f"icon {icon_name} not found")
                return ()
            w, h = img.size
            img.close()
            icon = (w, h, "png", icon_data)
            icons = (icon,)
            return icons
    return ()


class CaptureWindowModel:
    __slots__ = (
        "title", "geometry", "capture",
        "property_names", "dynamic_property_names", "internal_property_names",
        "signal_listeners",
    )

    def __init__(self, capture=None, title: str = "", geometry=None):
        self.title: str = title
        self.geometry = geometry
        self.capture = capture
        self.property_names: list[str] = [
            "title", "class-instance",
            "client-machine", "window-type",
            "size-constraints", "icons", "shadow",
            "depth",
        ]
        self.dynamic_property_names: list[str] = []
        self.internal_property_names: list[str] = ["content-type"]
        self.signal_listeners: dict[str, list[tuple]] = {}

    def __repr__(self):
        return f"CaptureWindowModel({self.capture} : {str(self.geometry):24})"

    def get_info(self) -> dict[str, Any]:
        info = {}
        c = self.capture
        if c:
            info["capture"] = c.get_info()
        return info

    def take_screenshot(self):
        return self.capture.take_screenshot()

    def get_image(self, x: int, y: int, width: int, height: int):
        ox, oy = self.geometry[:2]
        image = self.capture.get_image(ox + x, oy + y, width, height)
        if image and (ox > 0 or oy > 0):
            # adjust x and y of where the image is displayed on the client (target_x and target_y)
            # not where the image lives within the current buffer (x and y)
            image.set_target_x(x)
            image.set_target_y(y)
        return image

    def unmanage(self, exiting=False) -> None:
        """ subclasses may want to perform cleanup here """

    def suspend(self) -> None:
        """ subclasses may want to suspend pixel capture """

    def is_managed(self) -> bool:
        return True

    def is_tray(self) -> bool:
        return False

    def is_OR(self) -> bool:
        return False

    def has_alpha(self) -> bool:
        return False

    def uses_xshm(self) -> bool:
        return False

    def is_shadow(self) -> bool:
        return True

    def get_default_window_icon(self, _size: int = 48):
        return None

    def acknowledge_changes(self) -> None:
        """ only window models that use the X11 Damage extension use this method """

    def get_dimensions(self) -> tuple[int, int]:
        # used by get_window_info only
        return self.geometry[2:4]

    def get_geometry(self) -> tuple[int, int, int, int]:
        return self.geometry

    def get_property_names(self) -> list[str]:
        return self.property_names

    def get_dynamic_property_names(self) -> list[str]:
        return self.dynamic_property_names

    def get_internal_property_names(self) -> list[str]:
        return self.internal_property_names

    def get_property(self, prop: str):
        # subclasses can define properties as attributes:
        attr_name = prop.replace("-", "_")
        if hasattr(self, attr_name):
            return getattr(self, attr_name)
        # otherwise fallback to default behaviour:
        if prop == "title":
            return self.title
        if prop == "client-machine":
            return socket.gethostname()
        if prop == "window-type":
            return ["NORMAL"]
        if prop == "fullscreen":
            return False
        if prop == "shadow":
            return True
        if prop == "depth":
            return 24
        if prop == "scaling":
            return None
        if prop == "opacity":
            return None
        if prop == "size-constraints":
            size = self.get_dimensions()
            return {
                "maximum-size": size,
                "minimum-size": size,
                "base-size": size,
            }
        if prop == "class-instance":
            osn = get_generic_os_name()
            if osn == "Linux":
                try:
                    osn += "-" + get_linux_distribution()[0].replace(" ", "-")
                except Exception:  # pragma: no cover
                    pass
            return f"xpra-{osn.lower()}", f"Xpra {osn.replace('-', ' ')}"
        if prop == "icons":
            return get_os_icons()
        if prop == "content-type":
            return "desktop"
        raise AttributeError(f"invalid property {prop!r}")

    def get(self, name: str, default_value=None):
        try:
            return self.get_property(name)
        except AttributeError as e:
            log("get(%s, %s) %s on %s", name, default_value, e, self)
            return default_value

    def notify(self, prop: str) -> None:
        listeners = self.signal_listeners.get(prop)
        if listeners is None:
            log.warn(f"Warning: ignoring notify for {prop!r}")
            return
        PSpec = namedtuple("PSpec", ("name", ))
        pspec = PSpec(name=prop)
        for listener, *args in listeners:
            with log.trap_error(f"Error on {prop!r} signal listener {listener}"):
                listener(self, pspec, *args)

    def managed_connect(self, signal: str, *args):  # pragma: no cover
        self.connect(signal, *args)

    def connect(self, signal: str, *args):  # pragma: no cover
        prop = signal.split(":")[-1]  # notify::geometry
        if prop not in self.dynamic_property_names:
            log.warn(f"Warning: ignoring signal connect request: {args}")
            return
        self.signal_listeners.setdefault(prop, []).append(args)

    def disconnect(self, *args):  # pragma: no cover
        log.warn(f"Warning: ignoring signal disconnect request: {args}")
