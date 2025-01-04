# This file is part of Xpra.
# Copyright (C) 2018 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os.path
from io import BytesIO
from typing import TypeAlias

from xpra.os_util import gi_import
from xpra.util.env import first_time
from xpra.util.io import load_binary_file
from xpra.log import Logger

log = Logger("dbus", "notify")

IconData: TypeAlias = tuple[str, int, int, bytes]


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
    return None


def parse_image_path(path: str) -> IconData | None:
    if path and os.path.exists(path):
        Image = PIL_Image()
        if not Image:
            return None
        try:
            img = Image.open(path)
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
    buf = BytesIO()
    img.save(buf, "png")
    data = buf.getvalue()
    buf.close()
    w, h = img.size
    return "png", w, h, data


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
    buf = BytesIO()
    img.save(buf, "PNG")
    cpixels = buf.getvalue()
    buf.close()
    return "png", w, h, cpixels


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
