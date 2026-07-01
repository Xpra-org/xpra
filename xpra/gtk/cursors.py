# This file is part of Xpra.
# Copyright (C) 2012 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from collections.abc import Sequence

from xpra.os_util import gi_import, WIN32
from xpra.util.env import envbool, first_time
from xpra.log import Logger

Gdk = gi_import("Gdk")

log = Logger("gtk", "cursor")

SAVE_CURSORS = envbool("XPRA_SAVE_CURSORS", False)

cursor_names = {}
cursor_types = {}
missing_cursor_names = set()


def _init_map() -> None:
    for x in dir(Gdk.CursorType):
        if not x.isupper():
            # probably a method
            continue
        try:
            v = int(getattr(Gdk.CursorType, x))
            cursor_names[v] = x
            cursor_types[x] = v
        except (TypeError, ValueError):
            pass


_init_map()


def get_default_cursor() -> Gdk.Cursor:
    display = Gdk.Display.get_default()
    return Gdk.Cursor.new_from_name(display, "default")


def get_local_cursor(cursor_name: str):
    display = Gdk.Display.get_default()
    if not cursor_name or not display:
        return None
    try:
        cursor = Gdk.Cursor.new_from_name(display, cursor_name)
    except TypeError:
        log("Gdk.Cursor.new_from_name%s", (display, cursor_name), exc_info=True)
        cursor = None
    if cursor:
        log("Gdk.Cursor.new_from_name(%s, %s)=%s", display, cursor_name, cursor)
    else:
        gdk_cursor = cursor_types.get(cursor_name.upper())
        log("gdk_cursor(%s)=%s", cursor_name, gdk_cursor)
        if gdk_cursor:
            try:
                cursor = Gdk.Cursor.new_for_display(display, gdk_cursor)
                log("Cursor.new_for_display(%s, %s)=%s", display, gdk_cursor, cursor)
            except TypeError as e:
                log("new_Cursor_for_display(%s, %s)", display, gdk_cursor, exc_info=True)
                if first_time("cursor:%s" % cursor_name.upper()):
                    log.error("Error creating cursor %s: %s", cursor_name.upper(), e)
    if cursor:
        pixbuf = cursor.get_image()
        log("image=%s", pixbuf)
        return pixbuf
    if cursor_name not in missing_cursor_names:
        log("cursor name '%s' not found", cursor_name)
        missing_cursor_names.add(cursor_name)
    return None


def make_cursor(cursor_data: Sequence, xscale=1.0, yscale=1.0) -> Gdk.Cursor | None:
    from xpra.util.str_fn import Ellipsizer, repr_ellipsized, bytestostr, hexstr, memoryview_to_bytes
    from xpra.gtk.pixbuf import get_pixbuf_from_data
    from xpra.platform.gui import get_fixed_cursor_size
    # if present, try cursor by name:
    display = Gdk.Display.get_default()
    if not display:
        return None
    GdkPixbuf = gi_import("GdkPixbuf")
    from xpra.util.system import is_Wayland
    USE_LOCAL_CURSORS = envbool("XPRA_USE_LOCAL_CURSORS", not WIN32 and not is_Wayland())
    log("make_cursor(%s) has-name=%s, has-cursor-types=%s, xscale=%s, yscale=%s, USE_LOCAL_CURSORS=%s",
        Ellipsizer(cursor_data),
        len(cursor_data) >= 10, bool(cursor_types), xscale, yscale, USE_LOCAL_CURSORS)
    pixbuf = None
    if len(cursor_data) >= 10 and cursor_types and USE_LOCAL_CURSORS:
        cursor_name = bytestostr(cursor_data[9])
        pixbuf = get_local_cursor(cursor_name)
    # create cursor from the pixel data:
    encoding, _, _, w, h, xhot, yhot, serial, pixels = cursor_data[0:9]
    if encoding != "raw":
        log.warn("Warning: invalid cursor encoding: %s", encoding)
        return None
    if not pixbuf:
        if not pixels:
            log.warn("Warning: no cursor pixel data")
            log.warn(f" in cursor data {cursor_data}")
            return None
        if len(pixels) < w * h * 4:
            log.warn("Warning: not enough pixels provided in cursor data")
            log.warn(" %s needed and only %s bytes found:", w * h * 4, len(pixels))
            log.warn(" '%s')", repr_ellipsized(hexstr(pixels)))
            return None
        pixbuf = get_pixbuf_from_data(pixels, True, w, h, w * 4)
    else:
        w = pixbuf.get_width()
        h = pixbuf.get_height()
        pixels = pixbuf.get_pixels()
    x = max(0, min(xhot, w - 1))
    y = max(0, min(yhot, h - 1))
    csize = display.get_default_cursor_size()
    cmaxw, cmaxh = display.get_maximal_cursor_size()
    log("new %s cursor at %s,%s with serial=%#x, dimensions: %sx%s, len(pixels)=%s",
        encoding, xhot, yhot, serial, w, h, len(pixels))
    log("default cursor size is %s, maximum=%s", csize, (cmaxw, cmaxh))

    # always apply desktop-scale first:
    if xscale != 1 or yscale != 1:
        sw = round(w * xscale)
        sh = round(h * yscale)
        sx = round(x * xscale)
        sy = round(y * yscale)
        sw = max(1, sw)
        sh = max(1, sh)
        # ensure we honour the max size if there is one:
        if 0 < cmaxw < sw or 0 < cmaxh < sh:
            ratio = 1.0
            if cmaxw > 0:
                ratio = max(ratio, w / cmaxw)
            if cmaxh > 0:
                ratio = max(ratio, h / cmaxh)
            log("clamping cursor size to %ix%i using ratio=%s", cmaxw, cmaxh, ratio)
            sx, sy = round(sx / ratio), round(sy / ratio)
            sw, sh = min(cmaxw, round(sw / ratio)), min(cmaxh, round(sh / ratio))

        log("scaling cursor to %ix%i for desktop-scale %s/%s", sw, sh, xscale, yscale)
        pixbuf = pixbuf.scale_simple(sw, sh, GdkPixbuf.InterpType.BILINEAR)
        pixels = pixbuf.get_pixels()
        w, h, x, y = sw, sh, sx, sy

    fw, fh = get_fixed_cursor_size()
    # OS wants a fixed cursor size! (win32 does, and GTK doesn't do this for us)
    # we may have to paste it into a bigger pixbuf, or crop it:
    if fw > 0 and fh > 0 and (w, h) != (fw, fh):
        if w <= fw and h <= fh:
            log("pasting %ix%i cursor to fixed OS size %ix%i", w, h, fw, fh)
            try:
                from PIL import Image  # @UnresolvedImport pylint: disable=import-outside-toplevel
            except ImportError:
                return None
            img = Image.frombytes("RGBA", (w, h), memoryview_to_bytes(pixels), "raw", "BGRA", w * 4, 1)
            target = Image.new("RGBA", (fw, fh))
            target.paste(img, (0, 0, w, h))
            pixels = target.tobytes("raw", "BGRA")
            pixbuf = get_pixbuf_from_data(pixels, True, fw, fh, fw * 4)
        else:
            log("downscaling cursor from %ix%i to fixed OS size %ix%i", w, h, fw, fh)
            pixbuf = pixbuf.scale_simple(fw, fh, GdkPixbuf.InterpType.BILINEAR)
            xratio, yratio = w / fw, h / fh
            x, y = round(x / xratio), round(y / yratio)
    if SAVE_CURSORS:
        pixbuf.savev("cursor-%#x.png" % serial, "png", [], [])
    # clamp to pixbuf size:
    w = pixbuf.get_width()
    h = pixbuf.get_height()
    x = max(0, min(x, w - 1))
    y = max(0, min(y, h - 1))
    try:
        c = Gdk.Cursor.new_from_pixbuf(display, pixbuf, x, y)
    except RuntimeError as e:
        log.error("Error: failed to create cursor:")
        log.estr(e)
        log.error(" Gdk.Cursor.new_from_pixbuf%s", (display, pixbuf, x, y))
        log.error(" using size %ix%i with hotspot at %ix%i", w, h, x, y)
        c = None
    return c


def main() -> None:
    # pylint: disable=import-outside-toplevel
    from xpra.util.str_fn import csv
    from xpra.platform import program_context
    with program_context("Cursors", "Cursors"):
        print(csv(cursor_types))


if __name__ == "__main__":
    main()
