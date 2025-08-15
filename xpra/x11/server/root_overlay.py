# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import math
from collections.abc import Sequence

from xpra.os_util import gi_import
from xpra.util.str_fn import memoryview_to_bytes
from xpra.x11.bindings.core import get_root_xid
from xpra.x11.bindings.window import X11WindowBindings
from xpra.x11.bindings.fixes import XFixesBindings
from xpra.x11.bindings.composite import XCompositeBindings
from xpra.x11.error import xsync, xswallow, xlog
from xpra.codecs.argb.argb import unpremultiply_argb, bgra_to_rgba, bgra_to_rgbx, r210_to_rgbx, bgr565_to_rgbx
from cairo import OPERATOR_OVER, OPERATOR_SOURCE  # pylint: disable=no-name-in-module
from xpra.log import Logger

GLib = gi_import("GLib")
GObject = gi_import("GObject")
Gdk = gi_import("Gdk")
GdkX11 = gi_import("GdkX11")

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


def cairo_create(root_overlay: int):
    display = Gdk.Display.get_default()
    overlaywin = GdkX11.X11Window.foreign_new_for_display(display, root_overlay)
    return overlaywin.cairo_create()


def paint_overlay_monitors(cr, screen: Sequence) -> None:
    log("paint_overlay_monitors%s", (cr, screen))
    if len(screen) < 10:
        return
    display_name, width, height, width_mm, height_mm, monitors, work_x, work_y, work_width, work_height = screen[:10]
    assert display_name or width_mm or height_mm or True  # just silences pydev warnings
    # paint dark grey background for display dimensions:
    fill_rect(cr, (0.2, 0.2, 0.2), 0, 0, width, height)
    fill_rect(cr, (0.2, 0.2, 0.4), 0, 0, width, height)
    # paint lighter grey background for workspace dimensions:
    draw_rect(cr, (0.5, 0.5, 0.5), work_x, work_y, work_width, work_height)
    # paint each monitor with even lighter shades of grey:
    for m in monitors:
        if len(m) < 7:
            continue
        plug_name, plug_x, plug_y, plug_width, plug_height, plug_width_mm, plug_height_mm = m[:7]
        assert plug_name or plug_width_mm or plug_height_mm or True  # just silences pydev warnings
        draw_rect(cr, (0.7, 0.7, 0.7), plug_x, plug_y, plug_width, plug_height)
        if len(m) >= 10:
            dwork_x, dwork_y, dwork_width, dwork_height = m[7:11]
            draw_rect(cr, (1, 1, 1), dwork_x, dwork_y, dwork_width, dwork_height)


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
    display = Gdk.Display.get_default()
    overlaywin = GdkX11.X11Window.foreign_new_for_display(display, root_overlay)
    cr = overlaywin.cairo_create()
    paint_overlay_window(cr, window, x, y, image)


def paint_overlay_window(cr, window, x: int, y: int, image) -> None:
    log("paint_overlay_window%s", (cr, window, x, y, image))
    wx, wy = window.get_property("geometry")[:2]
    # FIXME: we should paint the root overlay directly
    # either using XCopyArea or XShmPutImage,
    # using GTK and having to unpremultiply then convert to RGB is just too slooooow
    width = image.get_width()
    height = image.get_height()
    rowstride = image.get_rowstride()
    img_data = image.get_pixels()
    rgb_format = image.get_pixel_format()
    log("update_root_overlay%s rgb_format=%s, img_data=%i (%s)",
        (window, x, y, image), rgb_format, len(img_data), type(img_data))
    operator = OPERATOR_SOURCE
    if rgb_format == "BGRA":
        img_data = unpremultiply_argb(img_data)
        img_data = bgra_to_rgba(img_data)
        operator = OPERATOR_OVER
    elif rgb_format == "BGRX":
        img_data = bgra_to_rgbx(img_data)
    elif rgb_format == "r210":
        # lossy...
        img_data = r210_to_rgbx(img_data, width, height, rowstride, width * 4)
        rowstride = width * 4
    elif rgb_format == "BGR565":
        img_data = bgr565_to_rgbx(img_data)
        rowstride *= 2
    else:
        raise ValueError(f"xync-xvfb root overlay paint code does not handle {rgb_format} pixel format")
    img_data = memoryview_to_bytes(img_data)
    log("update_root_overlay%s painting rectangle %s", (window, x, y, image), (wx + x, wy + y, width, height))
    from xpra.gtk.pixbuf import get_pixbuf_from_data
    pixbuf = get_pixbuf_from_data(img_data, True, width, height, rowstride)
    cr.new_path()
    cr.rectangle(wx + x, wy + y, width, height)
    cr.clip()
    Gdk.cairo_set_source_pixbuf(cr, pixbuf, wx + x, wy + y)
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
