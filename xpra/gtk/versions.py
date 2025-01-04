#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2009 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from typing import Any

GTK_VERSION_INFO: dict[str, tuple] = {}


def get_gtk_version_info() -> dict[str, Any]:
    from xpra.util.version import parse_version

    # update props given:
    global GTK_VERSION_INFO
    if GTK_VERSION_INFO:
        return GTK_VERSION_INFO.copy()

    def av(k, v) -> None:
        GTK_VERSION_INFO[k] = parse_version(v)

    def V(k, module, attr_name) -> None:
        v = getattr(module, attr_name, None)
        if v is not None:
            av(k, v)

    from xpra.os_util import gi_import
    # this isn't the actual version, (only shows as "3.0")
    # but still better than nothing:
    import gi
    V("gi", gi, "__version__")

    def giv(k: str, gimod: str, attr_name: str) -> None:
        mod = gi_import(gimod)
        if mod:
            V(k, mod, attr_name)

    giv("gobject", "GObject", "pygobject_version")
    giv("gtk", "Gtk", "_version")
    giv("gdk", "Gdk", "_version")
    giv("gobject", "GObject", "_version")
    giv("pixbuf", "GdkPixbuf", "_version")
    giv("pixbuf", "GdkPixbuf", "PIXBUF_VERSION")

    def MAJORMICROMINOR(name: str, module) -> None:
        try:
            v = tuple(getattr(module, x) for x in ("MAJOR_VERSION", "MICRO_VERSION", "MINOR_VERSION"))
            av(name, ".".join(str(x) for x in v))
        except Exception:
            pass

    MAJORMICROMINOR("gtk", gi_import("Gtk"))
    MAJORMICROMINOR("glib", gi_import("GLib"))
    try:
        import cairo
        av("cairo", parse_version(cairo.version_info))  # pylint: disable=no-member
    except ImportError:
        pass
    try:
        pango = gi_import("Pango")
        av("pango", parse_version(pango.version_string()))
    except ImportError:
        pass
    return GTK_VERSION_INFO.copy()
