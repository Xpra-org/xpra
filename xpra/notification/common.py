# This file is part of Xpra.
# Copyright (C) 2018 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os.path
from io import BytesIO
from typing import TypeAlias

from xpra.os_util import gi_import, POSIX, OSX
from xpra.util.env import first_time
from xpra.util.io import load_binary_file
from xpra.log import Logger

log = Logger("dbus", "notify")

IconData: TypeAlias = tuple[str, int, int, bytes]

SVG_SIZE = 96

ICON_EXTENSIONS = ("png", "xpm", )


def PIL_Image():
    try:
        # pylint: disable=import-outside-toplevel
        from PIL import Image
        return Image
    except ImportError:
        if first_time("parse-image-requires-pillow"):
            log.info("using notification icons requires python-pillow")
        return None


def parse_image_data(data) -> IconData | None:
    with log.trap_error("Error parsing icon data for notification"):
        width, height, rowstride, has_alpha, bpp, channels, pixels = data
        log("parse_image_data(%i, %i, %i, %s, %i, %i, %i bytes)",
            width, height, rowstride, bool(has_alpha), bpp, channels, len(pixels))
        Image = PIL_Image()
        if not Image:
            return None
        if channels == 4:
            rgb_format = "BGRA"
            fmt = "RGBA"
        elif channels == 3:
            rgb_format = "BGR"
            fmt = "RGB"
        else:
            raise ValueError(f"invalid number of channels: {channels}")
        if isinstance(pixels, (list, tuple)):
            pixels = bytes(pixels)
        img = Image.frombytes(fmt, (width, height), pixels, "raw", rgb_format, rowstride)
        if channels == 4 and not has_alpha:
            img = img.convert("RGB")
        return image_data(img)


def parse_image_path(path: str) -> IconData | None:
    log("parse_image_path(%s)", path)
    if path.startswith("file://"):
        path = path.removeprefix("file://")
    if not os.path.exists(path):
        log(" %r does not exist", path)
        return None
    Image = PIL_Image()
    if not Image:
        log(" cannot parse images without python-pillow")
        return None
    if path.endswith(".svg"):
        # note: this code path is currently unused,
        # because we don't include `svg` in `ICON_EXTENSIONS`
        # even if we did, `svg_to_png` requires GdkPixbuf,
        # which requires Gtk, which we do not want.
        from xpra.util.thread import is_main_thread
        if is_main_thread():
            try:
                from xpra.codecs.icon_util import svg_to_png
            except ImportError as e:
                log("cannot parse svg image %r: %s", path, e)
                return None
            svg_data = load_binary_file(path)
            png_data = svg_to_png(path, svg_data, SVG_SIZE, SVG_SIZE)
            if not png_data:
                log("svg_to_png failed")
                return None
            img = Image.open(BytesIO(png_data))
            return image_data(img)
        else:
            from threading import current_thread
            log.warn("Warning: cannot load SVG image %r", path)
            log.warn(" from %r thread", current_thread())
            log("parse_image_path(%s)", path, backtrace=True)
        return None
    try:
        img = Image.open(path)
        w, h = img.size
        maxsize = max(w, h)
        minsize = min(w, h)
        if maxsize > 100 or 0 < minsize < 48:
            img = img.resize((max(48, w * 100 // maxsize), max(48, h * 100 // maxsize)), Image.Resampling.BILINEAR)
        return image_data(img)
    except Exception as e:
        log(f"failed to open image {path!r}", exc_info=True)
        log.error("Error loading image for notification")
        log.error(f" using path {path!r}:")
        estr = str(e)
        if estr.endswith(f"{path!r}"):
            estr = estr[:-len(f"{path!r}")]
        log.error(f" {estr}")
    return None


def image_data(img) -> IconData:
    from xpra.codecs.image import to_png
    w, h = img.size
    return "png", w, h, to_png(img)


def get_notification_icon(icon_string: str) -> IconData | None:
    # this method *must* be called from the UI thread
    # since we may end up calling svg_to_png which uses Cairo
    #
    # the string may be:
    # * a path which we will load using pillow
    # * a name we look up in the current theme
    if not icon_string:
        return None
    MAX_SIZE = 256
    img = None
    w = h = 0
    from PIL import Image
    if os.path.isabs(icon_string):
        if os.path.exists(icon_string) and os.path.isfile(icon_string):
            try:
                if icon_string.endswith(".svg"):
                    from xpra.codecs.icon_util import svg_to_png
                    svg_data = load_binary_file(icon_string)
                    png_data = svg_to_png(icon_string, svg_data, MAX_SIZE, MAX_SIZE)
                    return "png", MAX_SIZE, MAX_SIZE, png_data
                # should we be using pillow.decoder.open_only here? meh
                img = Image.open(icon_string)
            except Exception as e:
                log("%s(%s)", Image.open, icon_string)
                log.warn("Warning: unable to load notification icon file")
                log.warn(" '%s'", icon_string)
                log.warn(" %s", e)
            else:
                w, h = img.size
        if not img:
            # we failed to load it using the absolute path,
            # so try to locate this icon without the path or extension:
            icon_string = os.path.splitext(os.path.basename(icon_string))[0]
    if not img:
        # try to find it in the theme:
        img = get_gtk_theme_icon(icon_string)
    if not img:
        return None
    if w > MAX_SIZE or h > MAX_SIZE:
        try:
            LANCZOS = Image.Resampling.LANCZOS
        except AttributeError:
            LANCZOS = Image.LANCZOS
        img = img.resize((MAX_SIZE, MAX_SIZE), LANCZOS)
        w = h = MAX_SIZE
    from xpra.codecs.image import to_png
    return "png", w, h, to_png(img)


def get_gtk_theme_icon(icon_string: str):
    # try to find it in the theme:
    try:
        Gtk = gi_import("Gtk")
        theme = Gtk.IconTheme.get_default()
    except ImportError:
        return None
    if not theme:
        return None
    try:
        icon = theme.load_icon(icon_string, Gtk.IconSize.BUTTON, 0)
    except Exception as e:
        log("failed to load icon '%s' from default theme: %s", icon_string, e)
        return None
    data = icon.get_pixels()
    w = icon.get_width()
    h = icon.get_height()
    rowstride = icon.get_rowstride()
    mode = "RGB"
    if icon.get_has_alpha():
        mode = "RGBA"
    from PIL import Image
    return Image.frombytes(mode, (w, h), data, "raw", mode, rowstride)


# Ensure that the hints are of the correct type:
def validated_hints(h: dict) -> dict[str, int | bool | str]:
    hints: dict[str, int | bool | str] = {}
    for attr, atype in {
        "action-icons": bool,
        "category": str,
        "desktop-entry": str,
        "resident": bool,
        "transient": bool,
        "x": int,
        "y": int,
        "urgency": int,
    }.items():
        if attr not in h:
            continue
        value = h.get(attr)
        try:
            validated = atype(value)
        except (ValueError, TypeError) as e:
            log.warn("Warning: unable to parse %r as a %s: %s", value, atype, e)
            continue
        else:
            hints[attr] = validated
    return hints


# dbus image / icon hints lookup:
# (try all attribute names from spec 0.9 onwards)
def image_data_hint(hints: dict) -> IconData | None:
    for attr in ("image-data", "image_data", "image-path", "image_path", "icon_data"):
        value: str = hints.pop(attr, "")
        if not value:
            continue
        if attr.endswith("path"):
            if not os.path.isabs(value) and POSIX and not OSX:
                from xpra.platform.posix.menu_helper import do_find_icon
                name = value
                value = do_find_icon(value, extensions=ICON_EXTENSIONS)
                log("do_find_icon(%s, %s)=%s", name, ICON_EXTENSIONS, value)
            icon_data = parse_image_path(value)
        else:
            icon_data = parse_image_data(value)
        if icon_data:
            log("parse_hints(..) using image-data from %r", attr)
            return icon_data
    return None


def decompress_image_data(icon_data: IconData) -> tuple[int, int, int, bool, int, int, bytearray]:
    try:
        from xpra.codecs.pillow.decoder import open_only  # pylint: disable=import-outside-toplevel
        img_data = icon_data[3]
        img = open_only(img_data, ("png",))
        w, h = img.size
        channels = len(img.mode)
        rowstride = w * channels
        has_alpha = img.mode == "RGBA"
        pixel_data = bytearray(img.tobytes("raw", img.mode))
        return w, h, rowstride, has_alpha, 8, channels, pixel_data
    except Exception as e:
        log("parse_hints(%s) error on image-data=%s", h, image_data, exc_info=True)
        log.error("Error parsing notification image:")
        log.estr(e)
        return 0, 0, 0, False, 0, 0, bytearray()
