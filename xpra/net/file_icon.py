# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

"""
Icon lookups for file transfers, from the file's mimetype, name or contents.
This does not use GTK: `Gio` maps the file to icon names,
and the xdg icon themes (pyxdg) map those names to icon files.
It can be called from any thread, but SVG-only icons can only be rendered from the main thread.
"""

import os
import struct
from functools import lru_cache

from xpra.os_util import gi_import, POSIX, OSX
from xpra.util.env import envint
from xpra.common import SizedBuffer
from xpra.log import Logger

log = Logger("file", "icon")

FILE_ICON_SIZE = envint("XPRA_FILE_ICON_SIZE", 48)
# `Gio.content_type_guess` only needs the start of the file to sniff its type:
GUESS_DATA_SIZE = 4096
PNG_HEADER = b"\x89PNG\r\n\x1a\n"


def get_gio():
    try:
        return gi_import("Gio")
    except (ImportError, ValueError) as e:
        log("no Gio: %s", e)
        return None


def guess_content_type(filename: str = "", mimetype: str = "", data: SizedBuffer = b"") -> str:
    Gio = get_gio()
    if not Gio:
        return mimetype
    if mimetype:
        if content_type := Gio.content_type_from_mime_type(mimetype):
            return content_type
    if not filename and not data:
        return ""
    content_type, uncertain = Gio.content_type_guess(filename or None, bytes(data[:GUESS_DATA_SIZE]) or None)
    log("content_type_guess(%r, %i bytes)=%s (uncertain=%s)", filename, len(data), content_type, uncertain)
    return content_type or ""


def get_icon_names(content_type: str) -> tuple[str, ...]:
    """ the themed icon names for this content type, most specific first, without the symbolic variants """
    names: list[str] = []
    if Gio := get_gio():
        gicon = Gio.content_type_get_icon(content_type)
        names += list(getattr(gicon, "get_names", tuple)())
        names.append(Gio.content_type_get_generic_icon_name(content_type) or "")
    elif "/" in content_type:
        # the freedesktop naming convention, ie: "application/pdf" -> "application-pdf", "application-x-generic"
        names += [content_type.replace("/", "-"), content_type.split("/")[0] + "-x-generic"]
    unique = dict.fromkeys(name for name in names if name and not name.endswith("-symbolic"))
    return tuple(unique)


def get_png_size(data: bytes) -> tuple[int, int]:
    if len(data) < 24 or not data.startswith(PNG_HEADER) or data[12:16] != b"IHDR":
        return 0, 0
    return struct.unpack(">II", data[16:24])


def scale_png(data: bytes, size: int) -> bytes:
    w, h = get_png_size(data)
    if not w or not h or (w <= size and h <= size and max(w, h) == size):
        return data
    try:
        from io import BytesIO
        from PIL import Image  # pylint: disable=import-outside-toplevel
        from xpra.codecs.image import to_png
        img = Image.open(BytesIO(data))
        img = img.convert("RGBA")
        scale = size / max(w, h)
        img = img.resize((max(1, round(w * scale)), max(1, round(h * scale))), Image.Resampling.LANCZOS)
        return to_png(img)
    except Exception as e:
        log("scale_png(%i bytes, %i) %s", len(data), size, e)
        # only use the unscaled icon if it isn't too big:
        return data if max(w, h) <= size * 2 else b""


def find_icon_file(names: tuple[str, ...], extensions: tuple[str, ...]) -> str:
    if not POSIX or OSX or not names:
        return ""
    try:
        from xpra.platform.posix.menu_helper import find_theme_icon, find_pixmap_icon
    except ImportError as e:
        log("find_icon_file(%s) %s", names, e)
        return ""
    return find_theme_icon(*names, extensions=extensions) or find_pixmap_icon(*names, extensions=extensions)


def load_png_icon(names: tuple[str, ...]) -> bytes:
    from xpra.codecs.icon_util import load_icon_from_file, svg_to_png
    # prefer raster icons, which we can use from any thread:
    if filename := find_icon_file(names, ("png", "xpm")):
        icondata = load_icon_from_file(filename)
        if icondata and icondata[1] == "png":
            return icondata[0]
    # `svg_to_png` can only be used from the main thread:
    from xpra.util.thread import is_main_thread
    if is_main_thread() and (filename := find_icon_file(names, ("svg", ))):
        icondata = load_icon_from_file(filename)
        if icondata and icondata[1] == "svg":
            return svg_to_png(filename, icondata[0], FILE_ICON_SIZE, FILE_ICON_SIZE)
    return b""


@lru_cache(maxsize=64)
def get_content_type_icon(content_type: str, size: int = FILE_ICON_SIZE) -> tuple[str, int, int, bytes] | None:
    if not content_type:
        return None
    try:
        names = get_icon_names(content_type)
        data = scale_png(load_png_icon(names), size)
        log("get_content_type_icon(%r, %i) names=%s, %i bytes", content_type, size, names, len(data))
        w, h = get_png_size(data)
        if not w or not h:
            return None
        return "png", w, h, data
    except Exception:
        # the icon is optional, don't make a fuss:
        log("get_content_type_icon(%r, %i)", content_type, size, exc_info=True)
    return None


def get_file_icon(filename: str = "", mimetype: str = "", data: SizedBuffer = b"",
                  size: int = FILE_ICON_SIZE) -> tuple[str, int, int, bytes] | None:
    return get_content_type_icon(guess_content_type(os.path.basename(filename), mimetype, data), size)


def main() -> int:
    import sys
    for arg in sys.argv[1:]:
        icon = get_file_icon(arg)
        print(f"{arg}: {icon[:3] if icon else None} {len(icon[3]) if icon else 0} bytes")
    return 0


if __name__ == "__main__":
    main()
