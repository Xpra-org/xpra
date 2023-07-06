#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2018-2022 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

"""
Utility functions for loading icons from files
"""

import os
import re
from io import BytesIO
from typing import Optional, Tuple

from xpra.util import envint, envbool, first_time, ellipsizer
from xpra.os_util import load_binary_file
from xpra.log import Logger

log = Logger("menu")

MAX_ICON_SIZE = envint("XPRA_XDG_MAX_ICON_SIZE", 0)
SVG_TO_PNG = envbool("XPRA_SVG_TO_PNG", True)

INKSCAPE_RE = b'\\sinkscape:[a-zA-Z]*=["a-zA-Z0-9]*'
INKSCAPE_BROKEN_SODIPODI_DTD = b'xmlns:sodipodi="http://inkscape.sourceforge.net/DTD/s odipodi-0.dtd"'
INKSCAPE_SODIPODI_DTD = b'xmlns:sodipodi="http://inkscape.sourceforge.net/DTD/sodipodi-0.dtd"'

large_icons = []

_Rsvg = None
def load_Rsvg():
    global _Rsvg
    if _Rsvg is None:
        import gi  #pylint: disable=import-outside-toplevel
        try:
            gi.require_version('Rsvg', '2.0')  # @UndefinedVariable
            from gi.repository import Rsvg  # pylint: disable=import-outside-toplevel @UnresolvedImport
            log("load_Rsvg() Rsvg=%s", Rsvg)
            _Rsvg = Rsvg
        except (ValueError, ImportError) as e:
            if first_time("no-rsvg"):
                log.warn("Warning: cannot resize svg icons,")
                log.warn(" the Rsvg bindings were not found:")
                log.warn(" %s", e)
            _Rsvg = False
    return _Rsvg


def load_icon_from_file(filename : str, max_size:int=MAX_ICON_SIZE) -> Optional[Tuple]:
    if os.path.isdir(filename):
        log("load_icon_from_file(%s, %i) path is a directory!", filename, max_size)
        return None
    log("load_icon_from_file(%s, %i)", filename, max_size)
    if filename.endswith("xpm"):
        from PIL import Image  #pylint: disable=import-outside-toplevel
        try:
            img = Image.open(filename)
            buf = BytesIO()
            img.save(buf, "PNG")
            pngicondata = buf.getvalue()
            buf.close()
            return pngicondata, "png"
        except ValueError as e:
            log(f"Image.open({filename}) {e}", exc_info=True)
        except Exception as e:
            log(f"Image.open({filename})", exc_info=True)
            log.error(f"Error loading {filename!r}:")
            log.estr(e)
    icondata = load_binary_file(filename)
    if not icondata:
        return None
    if filename.endswith("svg") and max_size and len(icondata)>max_size:
        #try to resize it
        size = len(icondata)
        pngdata = svg_to_png(filename, icondata)
        if pngdata:
            log("reduced size of SVG icon %s, from %i bytes to %i bytes as PNG",
                     filename, size, len(pngdata))
            icondata = pngdata
            filename = filename[:-3]+"png"
    log("got icon data from '%s': %i bytes", filename, len(icondata))
    if 0<max_size<len(icondata) and first_time(f"icon-size-warning-{filename}"):
        large_icons.append((filename, len(icondata)))
    return icondata, os.path.splitext(filename)[1].lstrip(".")

def svg_to_png(filename:str, icondata, w:int=128, h:int=128) -> Optional[bytes]:
    if not SVG_TO_PNG:
        return None
    Rsvg = load_Rsvg()
    log("svg_to_png%s Rsvg=%s", (filename, f"{len(icondata)} bytes", w, h), Rsvg)
    if not Rsvg:
        return None
    try:
        from cairo import ImageSurface, Context, FORMAT_ARGB32  #pylint: disable=no-name-in-module, import-outside-toplevel
        #'\sinkscape:[a-zA-Z]*=["a-zA-Z0-9]*'
        img = ImageSurface(FORMAT_ARGB32, w, h)
        ctx = Context(img)
        handle = Rsvg.Handle.new_from_data(data=icondata)
        dim = handle.get_dimensions()
        ctx.scale(w/dim.width, h/dim.height)
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
            #try again after stripping the bogus inkscape attributes
            #as some rsvg versions can't handle that (ie: Debian Bullseye)
            icondata = re.sub(INKSCAPE_RE, b"", icondata)
            return svg_to_png(filename, icondata, w, h)
        if icondata.find(INKSCAPE_BROKEN_SODIPODI_DTD)>0:
            icondata = icondata.replace(INKSCAPE_BROKEN_SODIPODI_DTD, INKSCAPE_SODIPODI_DTD)
            return svg_to_png(filename, icondata, w, h)
        log.error("Error: failed to convert svg icon")
        if filename:
            log.error(" '%s':", filename)
        log.error(" %i bytes, %s", len(icondata), ellipsizer(icondata))
        return None
