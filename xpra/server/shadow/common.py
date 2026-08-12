# This file is part of Xpra.
# Copyright (C) 2015 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.


from collections.abc import Sequence

from xpra.log import Logger

log = Logger("screen")

# the capture backends that can be selected with `--backend=NAME`,
# the first string is a short description, the others are extra details.
# (not all backends are available on all platforms,
# see `SHADOW_OPTIONS` in the platform specific `shadow_server` module)
SHADOW_BACKENDS: dict[str, Sequence[str]] = {
    "auto": (
        "Automatic runtime detection",
        "this is the default behaviour,",
        "this option should always find a suitable capture strategy",
        "and it may choose not to use a video stream",
    ),
    "x11": (
        "X11 screen capture",
        "copies the X11 server's pixel data,",
        "this option only requires the X11 bindings",
        "incompatible with Wayland sessions, the displays with XWayland will look blank",
    ),
    "xshm": (
        "X11 screen capture via shared memory",
        "identical to `x11` but faster thanks to the XShm extension",
    ),
    "gtk": (
        "GTK screen capture",
        "performance may vary,",
        "this option is not compatible with Wayland displays",
    ),
    "nvfbc": (
        "NVIDIA® Frame Buffer Capture",
        "this requires the proprietary module and libraries",
        "if available, this provides the fastest capture possible",
        "and also supports hardware video compression",
        "this option is only available for shadowing existing X11 sessions",
    ),
    "dxgi": (
        "DXGI Desktop Duplication",
        "the fastest capture option for MS Windows,",
        "it captures one monitor at a time and requires Direct3D 11",
    ),
    "gdi": (
        "GDI screen capture",
        "Legacy screen capture for MS Windows,",
        "the xpra server can use mixed encodings with this capture option",
    ),
    "pipewire": (
        "Native PipeWire capture",
        "PipeWire capture from the RemoteDesktop interface",
        "your desktop sessions must support the 'RemoteDesktop' dbus interface",
    ),
}


def backend_description(backend: str) -> str:
    details = SHADOW_BACKENDS.get(backend, ())
    return details[0] if details else backend


def parse_geometries(s: str) -> list[list[int]]:
    g = []
    for geometry_str in s.split("/"):
        if geometry_str:
            g.append(parse_geometry(geometry_str))
    return g


def parse_geometry(s) -> list[int]:
    try:
        parts = s.split("@")
        if len(parts) == 1:
            x = y = 0
        else:
            x, y = (int(v.strip(" ")) for v in parts[1].split("x"))
        w, h = (int(v.strip(" ")) for v in parts[0].split("x"))
        geometry = [x, y, w, h]
        log("capture geometry: %s", geometry)
        return geometry
    except ValueError:
        log("failed to parse geometry %r", s, exc_info=True)
        log.error("Error: invalid display geometry specified: %r", s)
        log.error(" use the format: WIDTHxHEIGHT@x,y")
        raise
