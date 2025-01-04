# This file is part of Xpra.
# Copyright (C) 2011 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os.path

from xpra.os_util import gi_import
from xpra.log import Logger

GdkPixbuf = gi_import("GdkPixbuf")

log = Logger("gtk", "util")


def get_icon_from_file(filename) -> GdkPixbuf.Pixbuf | None:
    if not filename:
        log("get_icon_from_file(%s)=None", filename)
        return None
    try:
        if not os.path.exists(filename):
            log.warn("Warning: cannot load icon, '%s' does not exist", filename)
            return None
        with open(filename, mode="rb") as f:
            data = f.read()
        loader = GdkPixbuf.PixbufLoader()
        loader.write(data)
        loader.close()
    except Exception as e:
        log("get_icon_from_file(%s)", filename, exc_info=True)
        log.error("Error: failed to load '%s'", filename)
        log.estr(e)
        return None
    pixbuf = loader.get_pixbuf()
    return pixbuf


def get_icon_pixbuf(icon_name: str) -> GdkPixbuf.Pixbuf | None:
    if not icon_name:
        log("get_icon_pixbuf(%s)=None", icon_name)
        return None
    with log.trap_error("Error loading icon pixbuf %s", icon_name):
        from xpra.platform.paths import get_icon_filename
        icon_filename = get_icon_filename(icon_name)
        log("get_pixbuf(%s) icon_filename=%s", icon_name, icon_filename)
        if icon_filename:
            return GdkPixbuf.Pixbuf.new_from_file(filename=icon_filename)
    return None


def get_pixbuf_from_data(rgb_data, has_alpha: bool, w: int, h: int, rowstride: int) -> GdkPixbuf.Pixbuf:
    glib = gi_import("GLib")
    data = glib.Bytes(rgb_data)
    return GdkPixbuf.Pixbuf.new_from_bytes(data, GdkPixbuf.Colorspace.RGB,
                                           has_alpha, 8, w, h, rowstride)


def pixbuf_save_to_memory(pixbuf, fmt="png") -> bytes:
    buf = []

    def save_to_memory(data, *_args, **_kwargs):
        buf.append(data)
        return True

    pixbuf.save_to_callbackv(save_to_memory, None, fmt, [], [])
    return b"".join(buf)
