# This file is part of Xpra.
# Copyright (C) 2020 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

"""
Toolkit independent helpers for building the window information dictionary
returned by the windows' `get_window_info()` method,
which the "Window Information" dialog displays.
The values are either pre-formatted strings or booleans.
"""

from typing import Any

from xpra.util.str_fn import csv, bytestostr

# the rows shown by the dialog, in order, `None` is a separator.
# keys found in the dictionary but missing from this list are only copied to the clipboard,
# rows for keys missing from the dictionary are hidden:
WINDOW_INFO_ROWS: tuple[tuple[str, str] | None, ...] = (
    ("wid", "Window ID"),
    ("title", "Title"),
    ("rendering", "Rendering"),
    ("override-redirect", "Override-Redirect"),
    ("state", "State"),
    ("attributes", "Attributes"),
    ("focused", "Focus"),
    ("buttons", "Button State"),
    ("fps", "Frames Per Second"),
    None,
    ("gravity", "Gravity"),
    ("content-types", "Content Types"),
    None,
    ("pixel-depth", "Pixel Depth"),
    ("alpha", "Alpha Channel"),
    ("opengl", "OpenGL"),
    None,
    ("geometry", "Geometry"),
    ("outer-geometry", "Outer Geometry"),
    ("inner-geometry", "Inner Geometry"),
    ("offsets", "Offsets"),
    ("frame-extents", "Frame Extents"),
    ("max-size", "Maximum Size"),
    ("size-constraints", "Size Constraints"),
    None,
    ("video-decoder", "Video Decoder"),
    None,
    ("backing", "Backing Properties"),
)

# shown in their own rows, or not at all:
BACKING_EXCLUDE = (
    "transparency",
    "size",
    "render-size",
    "offsets",
    "fps",
    "mmap",
    "type",
    "bit-depth",
    "video-decoder",
)


def dict_str(d) -> str:
    return "\n".join("%s : %s" % (k, v) for k, v in d.items())


def geom_str(geom) -> str:
    return "%ix%i at %i,%i" % (geom[2], geom[3], geom[0], geom[1])


def hsc(sc) -> str:
    # make the dict more human-readable
    ssc = dict((bytestostr(k), v) for k, v in sc.items())
    ssc.pop("gravity", None)
    return dict_str(ssc)


def pv(value) -> str:
    if isinstance(value, (tuple, list)):
        return csv(value)
    if isinstance(value, dict):
        return info_dict_str(value, ", ", ":")
    return str(value)


def info_dict_str(d: dict, sep="\n", eq="=", exclude=()) -> str:
    strdict = {k: pv(v) for k, v in d.items() if k not in exclude}
    return sep.join("%s%s%s" % (k, eq, v) for k, v in strdict.items() if v)


def get_backing_info(backing) -> dict[str, Any]:
    """
    The entries of the window information dictionary that come from the backing
    """
    if not backing:
        return {}
    fps = "n/a"
    if update_fps := getattr(backing, "update_fps", None):
        # noinspection calling-non-callable
        update_fps()
        fps = str(getattr(backing, "fps_value", "n/a"))
    binfo = backing.get_info()
    info: dict[str, Any] = {
        "rendering": binfo.get("type", "unknown"),
        "fps": fps,
        "backing": info_dict_str(binfo, exclude=BACKING_EXCLUDE),
        "size": csv(backing.size),
        "render-size": csv(backing.render_size),
        "backing-offsets": csv(backing.offsets),
    }
    if vdinfo := binfo.get("video-decoder"):
        info["video-decoder"] = info_dict_str(vdinfo)
    return info


def window_info_text(info: dict[str, Any]) -> str:
    """
    The plain text version of the window information, ie: for the clipboard
    """
    return "\n".join(f"{k}={v}" for k, v in info.items())
