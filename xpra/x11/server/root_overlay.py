# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import math
from collections.abc import Sequence

import cairo
from xpra.x11.bindings.core import get_root_xid
from xpra.x11.bindings.window import X11WindowBindings
from xpra.x11.bindings.fixes import XFixesBindings
from xpra.x11.bindings.composite import XCompositeBindings
from xpra.x11.error import xsync, xswallow, xlog
from xpra.cairo.context import xlib_surface_create
from xpra.cairo.image import make_image_surface, CAIRO_FORMATS
from xpra.log import Logger

log = Logger("screen")

XComposite = XCompositeBindings()
X11Window = X11WindowBindings()
XFixes = XFixesBindings()


def fill_rect(cr, shade: tuple[float, float, float], x: int, y: int, w: int, h: int) -> None:
    log("fill_rect%s", (shade, x, y, w, h))
    cr.new_path()
    cr.set_source_rgb(*shade)
    cr.rectangle(x, y, w, h)
    cr.fill()


def draw_rect(cr, shade: tuple[float, float, float], x: int, y: int, w: int, h: int) -> None:
    log("draw_rect%s", (shade, x, y, w, h))
    cr.new_path()
    cr.set_line_width(2)
    cr.set_source_rgb(*shade)
    cr.rectangle(x, y, w, h)
    cr.stroke()


def init_root_overlay() -> int:
    try:
        import cairo
        log(f"init_root_overlay() found cairo: {cairo}")
        with xsync:
            rxid = get_root_xid()
            root_overlay = XComposite.XCompositeGetOverlayWindow(rxid)
            log("init_root_overlay() root_overlay=%#x", root_overlay)
            if root_overlay:
                from xpra.x11.prop import prop_set
                prop_set(root_overlay, "WM_TITLE", "latin1", "RootOverlay")
                XFixes.AllowInputPassthrough(root_overlay)
                log("init_root_overlay() done AllowInputPassthrough(%#x)", root_overlay)
                return root_overlay
    except Exception as e:
        log("XCompositeGetOverlayWindow(%#x)", rxid, exc_info=True)
        log.error("Error setting up xvfb synchronization:")
        log.estr(e)
        release_root_overlay(root_overlay)
    return 0


def release_root_overlay(xid: int) -> None:
    with xswallow:
        XComposite.XCompositeReleaseOverlayWindow(xid)


def paint_overlay_monitors(cr, monitors: dict[int, dict]) -> None:
    log("paint_overlay_monitors%s", (cr, monitors))
    geometries = [g for g in (mdef.get("geometry", ()) for mdef in monitors.values()) if len(g) == 4]
    if not geometries:
        return
    # paint dark grey background for display dimensions:
    width = max(x + w for x, _, w, _ in geometries)
    height = max(y + h for _, y, _, h in geometries)
    fill_rect(cr, (0.2, 0.2, 0.2), 0, 0, width, height)
    fill_rect(cr, (0.2, 0.2, 0.4), 0, 0, width, height)
    # paint each monitor with lighter shades of grey, and its workarea in white:
    for mdef in monitors.values():
        geometry = mdef.get("geometry", ())
        if len(geometry) == 4:
            draw_rect(cr, (0.7, 0.7, 0.7), *geometry)
        workarea = mdef.get("workarea", ())
        if len(workarea) == 4:
            draw_rect(cr, (1, 1, 1), *workarea)


def paint_root_overlay_windows(cr, windows: Sequence) -> None:
    log("paint_root_overlay_windows(%s)",windows)
    for window in windows:
        w, h = window.get_property("geometry")[2:4]
        image = window.get_image(0, 0, w, h)
        if not image:
            continue
        paint_overlay_window(cr, window, 0, 0, image)
        paint_overlay_frame(cr, window)


def update_root_overlay(root_overlay: int, window, x: int, y: int, image) -> None:
    log("update_root_overlay%s", (root_overlay, window, x, y, image))
    surface = xlib_surface_create(root_overlay)
    cr = cairo.Context(surface)
    paint_overlay_window(cr, window, x, y, image)


def paint_overlay_window(cr, window, x: int, y: int, image) -> None:
    log("paint_overlay_window%s", (cr, window, x, y, image))
    wx, wy = window.get_property("geometry")[:2]
    width = image.get_width()
    height = image.get_height()
    rowstride = image.get_rowstride()
    img_data = image.get_pixels()
    rgb_format = image.get_pixel_format()
    log("paint_overlay_window%s rgb_format=%s, img_data=%i (%s)",
        (window, x, y, image), rgb_format, len(img_data), type(img_data))
    cairo_fmt = next((fmt for fmt, fmts in CAIRO_FORMATS.items() if rgb_format in fmts), None)
    if cairo_fmt is None:
        raise ValueError(f"root overlay paint code does not handle {rgb_format!r} pixel format")
    img_surface = make_image_surface(cairo_fmt, rgb_format, img_data, width, height, rowstride)
    operator = cairo.OPERATOR_OVER if rgb_format == "BGRA" else cairo.OPERATOR_SOURCE
    log("paint_overlay_window%s painting rectangle %s", (window, x, y, image), (wx + x, wy + y, width, height))
    cr.new_path()
    cr.rectangle(wx + x, wy + y, width, height)
    cr.clip()
    cr.set_source_surface(img_surface, wx + x, wy + y)
    cr.set_operator(operator)
    cr.paint()
    with xlog:
        image.free()


def paint_overlay_frame(cr, window) -> None:
    x, y, w, h = window.get_property("geometry")[:4]
    frame = window.get_property("frame")
    log("paint_overlay_frame(%s, %s) frame=%s", cr, window, frame)
    if frame and tuple(frame) != (0, 0, 0, 0):
        left, right, top, bottom = frame
        # always add a little something, so we can see the edge:
        left = max(1, left)
        right = max(1, right)
        top = max(1, top)
        bottom = max(1, bottom)
        rectangles = (
            (x - left, y, left, h, True),  # left side
            (x - left, y - top, w + left + right, top, True),  # top
            (x + w, y, right, h, True),  # right
            (x - left, y + h, w + left + right, bottom, True),  # bottom
        )
    else:
        rectangles = (
            (x, y, w, h, False),
        )
    log("rectangles for window frame=%s and geometry=%s : %s", frame, (x, y, w, h), rectangles)
    for x, y, w, h, fill in rectangles:
        cr.new_path()
        cr.set_source_rgb(0.1, 0.1, 0.1)
        cr.set_line_width(1)
        cr.rectangle(x, y, w, h)
        if fill:
            cr.fill()
        else:
            cr.stroke()


def paint_overlay_pointer(cr, x: int, y: int) -> None:
    log("paint_overlay_pointer(%s, %i, %i)", cr, x, y)
    cr.set_source_rgb(1.0, 0.5, 0.7)
    cr.new_path()
    cr.arc(x, y, 10.0, 0, 2.0 * math.pi)
    cr.stroke_preserve()
    cr.set_source_rgb(0.3, 0.4, 0.6)
    cr.fill()
