#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2012 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.util.objects import AdHocStruct
from xpra.log import Logger

log = Logger("shadow")


def screenshot(filename: str) -> int:
    # pylint: disable=import-outside-toplevel
    from xpra.x11.xroot_props import get_root_size
    from xpra.gtk.util import get_default_root_window
    from xpra.x11.shadow.backends import CAPTURE_BACKENDS
    from xpra.server.shadow.shadow_server_base import try_setup_capture
    root = get_default_root_window()
    capture = try_setup_capture(CAPTURE_BACKENDS, "auto", root)
    capture.refresh()
    w, h = get_root_size()
    image = capture.get_image(0, 0, w, h)
    log(f"snapshot: {capture.get_image}(0, 0, {w}, {h})={image}")
    from xpra.codecs.image import to_pil_encoding
    data = to_pil_encoding(image, "png", True)
    with open(filename, "wb") as f:
        f.write(data)
    return 0


def main(*args) -> int:
    assert len(args) > 0
    if args[0].endswith(".png"):
        return screenshot(args[0])

    def cb(title, geom):
        s = AdHocStruct()
        s.title = title
        s.geometry = geom
        return s

    from xpra.x11.gtk import gdk_display_source  # pylint: disable=import-outside-toplevel, no-name-in-module
    gdk_display_source.init_gdk_display_source()  # @UndefinedVariable
    from xpra.x11.shadow.filter import window_matches
    for w in window_matches(args, cb):
        print(f"{w}")
    return 0


if __name__ == "__main__":
    import sys

    if len(sys.argv) == 1:
        cmd = sys.argv[0]
        print(f"usage: {cmd} filename.png")
        print(f"usage: {cmd} windowname|windowpid")
        r = 1
    else:
        r = main(*sys.argv[1:])
    sys.exit(r)
