# This file is part of Xpra.
# Copyright (C) 2015 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.


from xpra.log import Logger

log = Logger("screen")


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
