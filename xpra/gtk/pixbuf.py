# This file is part of Xpra.
# Copyright (C) 2011 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os.path
from collections.abc import Sequence

from xpra.common import SizedBuffer
from xpra.codecs.image_type import get_image_type
from xpra.os_util import gi_import
from xpra.util.str_fn import csv, hexstr
from xpra.log import Logger

GdkPixbuf = gi_import("GdkPixbuf")

log = Logger("gtk", "util")

# the only GdkPixbuf loader modules we allow, all the others are disabled process-wide,
# (this also applies to the icons loaded by GTK itself, so `png` and `svg` should always be included):
PIXBUF_FORMATS: Sequence[str] = tuple(x.strip() for x in os.environ.get("XPRA_PIXBUF_FORMATS", "png,jpeg,svg").split(",") if x.strip())


def get_library(*names: str):
    # GLib and GdkPixbuf are already loaded, so this finds the libraries they are using without touching the filesystem:
    from ctypes import CDLL
    for name in names:
        try:
            return CDLL(name)
        except OSError:
            continue
    return None


def restrict_formats(formats: Sequence[str] = PIXBUF_FORMATS) -> list[str]:
    """
    Disables every GdkPixbuf loader module not listed in `formats`.
    PyGObject hands us copies of the `GdkPixbufFormat` structures,
    so `set_disabled` has to be called on the library's own instances via ctypes.
    Returns the list of formats that were disabled.
    """
    from ctypes import Structure, POINTER, c_void_p, c_int, string_at
    lib = get_library("libgdk_pixbuf-2.0.so.0", "libgdk_pixbuf-2.0-0.dll", "libgdk_pixbuf-2.0.0.dylib")
    glib = get_library("libglib-2.0.so.0", "libglib-2.0-0.dll", "libglib-2.0.0.dylib")
    if not lib or not glib:
        log.warn("Warning: unable to restrict the GdkPixbuf loaders to %s", csv(formats))
        return []

    class GSList(Structure):
        pass

    GSList._fields_ = [("data", c_void_p), ("next", POINTER(GSList))]
    lib.gdk_pixbuf_get_formats.restype = POINTER(GSList)
    lib.gdk_pixbuf_format_get_name.argtypes = [c_void_p]
    lib.gdk_pixbuf_format_get_name.restype = c_void_p
    lib.gdk_pixbuf_format_set_disabled.argtypes = [c_void_p, c_int]
    glib.g_free.argtypes = [c_void_p]
    glib.g_slist_free.argtypes = [POINTER(GSList)]
    disabled = []
    head = node = lib.gdk_pixbuf_get_formats()
    while node:
        fmt = node.contents.data
        name_ptr = lib.gdk_pixbuf_format_get_name(fmt)
        name = string_at(name_ptr).decode() if name_ptr else ""
        glib.g_free(name_ptr)
        if name not in formats:
            lib.gdk_pixbuf_format_set_disabled(fmt, 1)
            disabled.append(name)
        node = node.contents.next
    glib.g_slist_free(head)
    log("restrict_formats(%s) disabled: %s", formats, csv(disabled))
    return disabled


restrict_formats()


def load_pixbuf(data: SizedBuffer, types: Sequence[str] = PIXBUF_FORMATS) -> GdkPixbuf.Pixbuf:
    """
    Validates the image header before handing the data to the GdkPixbuf loader module for that type,
    so the loader never gets to sniff the data and pick a different module.
    """
    itype = get_image_type(data) or "unknown"
    if itype not in types or itype not in PIXBUF_FORMATS:
        raise ValueError(f"invalid data: {itype}, not recognized as {csv(t for t in types if t in PIXBUF_FORMATS)}, header: " + hexstr(data[:64]))
    loader = GdkPixbuf.PixbufLoader.new_with_type(itype)
    try:
        loader.write(data)
    finally:
        loader.close()
    return loader.get_pixbuf()


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
        return load_pixbuf(data)
    except Exception as e:
        log("get_icon_from_file(%s)", filename, exc_info=True)
        log.error("Error: failed to load '%s'", filename)
        log.estr(e)
        return None


def get_icon_pixbuf(icon_name: str) -> GdkPixbuf.Pixbuf | None:
    if not icon_name:
        log("get_icon_pixbuf(%s)=None", icon_name)
        return None
    with log.trap_error("Error loading icon pixbuf %s", icon_name):
        icon_filename = icon_name
        if not os.path.isabs(icon_name):
            from xpra.platform.paths import get_icon_filename
            icon_filename = get_icon_filename(icon_name)
        log("get_pixbuf(%s) icon_filename=%r", icon_name, icon_filename)
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
