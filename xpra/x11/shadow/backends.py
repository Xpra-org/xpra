#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2012 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from collections.abc import Callable

from xpra.util.env import envbool
from xpra.x11.shadow.ximage_capture import XImageCapture
from xpra.log import Logger

log = Logger("x11", "shadow")

nvfbc_failed = False


def setup_nvfbc_capture():
    global nvfbc_failed
    if nvfbc_failed:
        return None
    NVFBC = envbool("XPRA_SHADOW_NVFBC", True)
    if not NVFBC:
        return None
    try:
        from xpra.codecs.nvidia.nvfbc.capture import get_capture_module, get_capture_instance
        nvfbc = get_capture_module()
        if nvfbc:
            nvfbc.init_nvfbc_library()
        from xpra.gtk.util import get_default_root_window
        root = get_default_root_window()
        ww, wh = root.get_geometry()[2:4]
        capture = get_capture_instance()
        capture.init_context(ww, wh)
        capture.refresh()
        image = capture.get_image(0, 0, ww, wh)
        assert image, "test capture failed"
        return capture
    except Exception:
        log("NvFBC Capture is not available", exc_info=True)
        nvfbc_failed = True
        return None


def setup_gstreamer_capture():
    GSTREAMER: bool = envbool("XPRA_SHADOW_GSTREAMER", False)
    if not GSTREAMER:
        return None
    from xpra.gtk.util import get_default_root_window
    root = get_default_root_window()
    xid = root.get_xid()
    ww, wh = root.get_geometry()[2:4]
    from xpra.codecs.gstreamer.capture import Capture
    el = "ximagesrc"
    if xid >= 0:
        el += f" xid={xid} startx=0 starty=0"
    if ww > 0:
        el += f" endx={ww}"
    if wh > 0:
        el += f" endy={wh}"
    capture = Capture(el, width=ww, height=wh)
    capture.start()
    image = capture.get_image(0, 0, ww, wh)
    if not image:
        log("gstreamer capture failed to return an image")
        return None
    return capture


def setup_xshm_capture():
    XSHM = envbool("XPRA_SHADOW_XSHM", True)
    if not XSHM:
        return None
    try:
        from xpra.x11.bindings.ximage import XImageBindings  # pylint: disable=import-outside-toplevel
        XImage = XImageBindings()
        from xpra.x11.bindings.shm import XShmBindings
        XShm = XShmBindings()
    except ImportError as e:
        log(f"not using X11 capture using bindings: {e}")
        return None
    xid = XImage.get_root_xid()
    if XShm.has_XShm():
        return XImageCapture(xid)
    return None


def setup_gtk_capture():
    from xpra.gtk.util import get_default_root_window
    from xpra.gtk.capture import GTKImageCapture
    root = get_default_root_window()
    return GTKImageCapture(root)


CAPTURE_BACKENDS: dict[str, Callable] = {
    "nvfbc": setup_nvfbc_capture,
    "gstreamer": setup_gstreamer_capture,
    "xshm": setup_xshm_capture,
    "x11": setup_xshm_capture,
    "gtk": setup_gtk_capture,
}
