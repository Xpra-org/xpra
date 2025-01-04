#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2018 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

"""
Utility functions for loading icons from files
"""

import os
import re
from io import BytesIO

from xpra.util.str_fn import Ellipsizer
from xpra.util.env import envint, envbool, first_time, SilenceWarningsContext
from xpra.os_util import gi_import
from xpra.util.io import load_binary_file
from xpra.log import Logger

log = Logger("menu")

MAX_ICON_SIZE = envint("XPRA_XDG_MAX_ICON_SIZE", 0)
SVG_TO_PNG = envbool("XPRA_SVG_TO_PNG", True)

INKSCAPE_RE = b'\\sinkscape:[a-zA-Z]*=["a-zA-Z0-9]*'
INKSCAPE_BROKEN_SODIPODI_DTD = b'xmlns:sodipodi="http://inkscape.sourceforge.net/DTD/s odipodi-0.dtd"'
INKSCAPE_SODIPODI_DTD = b'xmlns:sodipodi="http://inkscape.sourceforge.net/DTD/sodipodi-0.dtd"'

large_icons = []

_rsvg = None


def load_rsvg():
    global _rsvg
    if _rsvg is None:
        try:
            rsvg = gi_import("Rsvg")
            log(f"load_Rsvg() {rsvg=}")
            _rsvg = rsvg
        except (ValueError, ImportError) as e:
            if first_time("no-rsvg"):
                log.warn("Warning: cannot resize svg icons,")
                log.warn(" the Rsvg bindings were not found:")
                log.warn(" %s", e)
            _rsvg = False
    return _rsvg


def load_icon_from_file(filename: str, max_size: int = MAX_ICON_SIZE) -> tuple:
    if os.path.isdir(filename):
        log("load_icon_from_file(%s, %i) path is a directory!", filename, max_size)
        return ()
    log("load_icon_from_file(%s, %i)", filename, max_size)
    if filename.endswith("xpm"):
        img = None
        try:
            from PIL import Image  # pylint: disable=import-outside-toplevel
            img = Image.open(filename)
            buf = BytesIO()
            img.save(buf, "PNG")
            pngicondata = buf.getvalue()
            buf.close()
            return pngicondata, "png"
        except (ValueError, ImportError) as e:
            log(f"Image.open({filename}) {e}", exc_info=True)
        except Exception as e:
            log(f"Image.open({filename})", exc_info=True)
            log.error(f"Error loading {filename!r}:")
            log.estr(e)
        finally:
            if img:
                img.close()
    icondata = load_binary_file(filename)
    if not icondata:
        return ()
    if filename.endswith("svg") and max_size and len(icondata) > max_size:
        # try to resize it
        size = len(icondata)
        pngdata = svg_to_png(filename, icondata)
        if pngdata:
            log(f"reduced size of SVG icon {filename}, from {size} bytes to {len(pngdata)} bytes as PNG")
            icondata = pngdata
            filename = filename[:-3] + "png"
    log("got icon data from '%s': %i bytes", filename, len(icondata))
    if 0 < max_size < len(icondata) and first_time(f"icon-size-warning-{filename}"):
        large_icons.append((filename, len(icondata)))
    return icondata, os.path.splitext(filename)[1].lstrip(".")


def svg_to_png(filename: str, icondata, w: int = 128, h: int = 128) -> bytes:
    if not SVG_TO_PNG:
        return b""
    rsvg = load_rsvg()
    log("svg_to_png%s rsvg=%s", (filename, f"{len(icondata)} bytes", w, h), rsvg)
    if not rsvg:
        return b""
    try:
        # pylint: disable=no-name-in-module, import-outside-toplevel
        from cairo import ImageSurface, Context, Format
        img = ImageSurface(Format.ARGB32, w, h)
        ctx = Context(img)
        handle = rsvg.Handle.new_from_data(data=icondata)
        if hasattr(handle, "render_document"):
            # Rsvg version 2.46 and later:
            rect = rsvg.Rectangle()
            rect.x = rect.y = 0
            rect.width = w
            rect.height = h
            if not handle.render_document(ctx, rect):
                raise RuntimeError(f"{handle}.render_document failed")
        else:
            with SilenceWarningsContext():
                dim = handle.get_dimensions()
                ctx.scale(w / dim.width, h / dim.height)
                handle.render_cairo(ctx)
        del handle
        img.flush()
        buf = BytesIO()
        img.write_to_png(buf)
        icondata = buf.getvalue()
        buf.close()
        img.finish()
        return icondata
    except Exception:
        log("svg_to_png%s", (icondata, w, h), exc_info=True)
        if re.findall(INKSCAPE_RE, icondata):
            # try again after stripping the bogus inkscape attributes
            # as some rsvg versions can't handle that (ie: Debian Bullseye)
            icondata = re.sub(INKSCAPE_RE, b"", icondata)
            return svg_to_png(filename, icondata, w, h)
        if icondata.find(INKSCAPE_BROKEN_SODIPODI_DTD) > 0:
            icondata = icondata.replace(INKSCAPE_BROKEN_SODIPODI_DTD, INKSCAPE_SODIPODI_DTD)
            return svg_to_png(filename, icondata, w, h)
        log.error("Error: failed to convert svg icon")
        if filename:
            log.error(" '%s':", filename)
        log.error(" %i bytes, %s", len(icondata), Ellipsizer(icondata))
        return b""
