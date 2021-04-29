#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2018-2020 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

"""
Utility functions for loading icons from files
"""

import os
import re

from io import BytesIO

from xpra.util import envint, first_time, ellipsizer
from xpra.os_util import load_binary_file
from xpra.log import Logger

log = Logger("menu")

MAX_ICON_SIZE = envint("XPRA_XDG_MAX_ICON_SIZE", 65536)

INKSCAPE_RE = b'\\sinkscape:[a-zA-Z]*=["a-zA-Z0-9]*'

large_icons = []

_Rsvg = None
def load_Rsvg():
    global _Rsvg
    if _Rsvg is None:
        import gi  #pylint: disable=import-outside-toplevel
        try:
            gi.require_version('Rsvg', '2.0')
            from gi.repository import Rsvg
            log("load_Rsvg() Rsvg=%s", Rsvg)
            _Rsvg = Rsvg
        except (ValueError, ImportError) as e:
            if first_time("no-rsvg"):
                log.warn("Warning: cannot resize svg icons,")
                log.warn(" the Rsvg bindings were not found:")
                log.warn(" %s", e)
            _Rsvg = False
    return _Rsvg


def load_icon_from_file(filename, max_size=MAX_ICON_SIZE):
    log("load_icon_from_file(%s)", filename)
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
            log("Image.open(%s)", filename, exc_info=True)
        except Exception as e:
            log("Image.open(%s)", filename, exc_info=True)
            log.error("Error loading '%s':", filename)
            log.error(" %s", e)
    icondata = load_binary_file(filename)
    if not icondata:
        return None
    if filename.endswith("svg") and len(icondata)>max_size:
        #try to resize it
        size = len(icondata)
        pngdata = svg_to_png(filename, icondata)
        if pngdata:
            log("reduced size of SVG icon %s, from %i bytes to %i bytes as PNG",
                     filename, size, len(pngdata))
            icondata = pngdata
            filename = filename[:-3]+"png"
    log("got icon data from '%s': %i bytes", filename, len(icondata))
    if len(icondata)>max_size and first_time("icon-size-warning-%s" % filename):
        global large_icons
        large_icons.append((filename, len(icondata)))
    return icondata, os.path.splitext(filename)[1].lstrip(".")

def svg_to_png(filename, icondata, w=128, h=128):
    Rsvg = load_Rsvg()
    if not Rsvg:
        return None
    try:
        from cairo import ImageSurface, Context, FORMAT_ARGB32  #pylint: disable=no-name-in-module, import-outside-toplevel
        #'\sinkscape:[a-zA-Z]*=["a-zA-Z0-9]*'
        img = ImageSurface(FORMAT_ARGB32, w, h)
        ctx = Context(img)
        handle = Rsvg.Handle.new_from_data(icondata)
        handle.render_cairo(ctx)
        buf = BytesIO()
        img.write_to_png(buf)
        icondata = buf.getvalue()
        buf.close()
        return icondata
    except Exception:
        log("svg_to_png%s", (icondata, w, h), exc_info=True)
        if re.findall(INKSCAPE_RE, icondata):
            #try again after stripping the bogus inkscape attributes
            #as some rsvg versions can't handle that (ie: Debian Bullseye)
            icondata = re.sub(INKSCAPE_RE, b"", icondata)
            return svg_to_png(filename, icondata, w, h)
        log.error("Error: failed to convert svg icon")
        if filename:
            log.error(" '%s':", filename)
        log.error(" %i bytes, %s", len(icondata), ellipsizer(icondata))
