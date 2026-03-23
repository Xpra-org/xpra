# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys
from collections import namedtuple

from xpra.client.gui.window_border import WindowBorder
from xpra.util.env import first_time
from xpra.client.base.stub import StubClientMixin
from xpra.log import Logger

log = Logger("window")


def show_border_help() -> None:
    if not first_time("border-help"):
        return
    log.info(" border format: color[,size][:off]")
    log.info("  eg: red,10")
    log.info("  eg: ,5")
    log.info("  eg: auto,5")
    log.info("  eg: blue")


RGBColor = namedtuple("RGBColor", ("red", "green", "blue"))


def parse_color(color_str: str) -> RGBColor:
    if "gi.repository.Gtk" in sys.modules:
        try:
            from xpra.gtk.widget import color_parse
            color = color_parse(color_str)
            assert color is not None
            return RGBColor(int(color.red // 256), int(color.green // 256), int(color.blue // 256))
        except Exception as e:
            log(f"gtk failed to parse border color '{color_str!r}'")
            if str(e):
                log(" %s", e)
    # try pillow:
    try:
        from PIL import ImageColor
        return RGBColor(*ImageColor.getrgb(color_str))
    except ValueError:
        log(f"pillow failed to parse border color '{color_str!r}'")

    log.warn(f"Warning: failed to parse border color {color_str!r}")
    show_border_help()
    # use red:
    return RGBColor(256, 0, 0)


def parse_border(border_str="", display_name="", warn=False) -> WindowBorder:
    # ie: "auto,5:off"
    parts = [x.strip() for x in border_str.replace(",", ":").split(":", 2)]
    color_str = parts[0]
    if color_str.lower() in ("none", "no", "off", "0"):
        return WindowBorder(False)
    if color_str.lower() == "help":
        show_border_help()
        return WindowBorder(False)
    if color_str in ("auto", ""):
        from hashlib import sha256
        m = sha256()
        if display_name:
            m.update(display_name.encode("utf8"))
        color_str = "#%s" % m.hexdigest()[:6]
        log(f"border color derived from {display_name}: {color_str}")
    color = parse_color(color_str)
    alpha = 0.6
    size = 4
    enabled = parts[-1] != "off"
    if enabled and len(parts) >= 2:
        size_str = parts[1]
        try:
            size = int(size_str)
        except Exception as e:
            if warn:
                log.warn(f"Warning: invalid border size specified {size_str!r}")
                log.warn(f" {e}")
                show_border_help()
        if size <= 0:
            log(f"border size is {size}, disabling it")
            enabled = False
            size = 0
        if size >= 45:
            log.warn(f"Warning: border size is too large: {size}, clipping it")
            size = 45
    border = WindowBorder(enabled, color.red / 256.0, color.green / 256.0, color.blue / 256.0, alpha, size)
    log("parse_border(%s)=%s", border_str, border)
    return border


class WindowBorderClient(StubClientMixin):
    """
    Adds support for the window border:
    parse it or generate it from the connection info.
    """

    def __init__(self):
        self.border = WindowBorder(False)
        self.border_str = "no"

    def init(self, opts) -> None:
        self.border_str = opts.border
        if opts.border:
            self.border = parse_border(self.border_str)

    def setup_connection(self, conn) -> None:
        display_name = getattr(self, "display_desc", {}).get("display_name", "")
        if display_name:
            # now that we have display_desc, parse the border again:
            self.border = parse_border(self.border_str, display_name)

    def get_border(self):
        if self.border:
            return self.border.clone()
        return None
